"""Shared Google service-account authentication for OpenMontage tools.

Lets the Google provider tools (``google_tts``, ``google_imagen``)
authenticate with a service-account JSON key file via OAuth Bearer tokens —
in addition to the existing API-key path. This is what makes
``GOOGLE_APPLICATION_CREDENTIALS`` actually work end to end.

The ``google-auth`` package is imported lazily so this module never adds an
import-time cost for tools that only use API keys, and so a missing dependency
surfaces as an actionable runtime error rather than a hard import failure.
"""

from __future__ import annotations

import os
import atexit
import json
import signal
import tempfile
from typing import Any

# Broad scope that covers Cloud Text-to-Speech and Vertex AI prediction.
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def resolve_google_location(location: str | None = None) -> str:
    """Return a Vertex location, treating blank env values as unset."""

    return location or os.environ.get("GOOGLE_CLOUD_LOCATION") or "us-central1"


# Shared constants for long-running Google/Vertex AI generation calls (e.g. music, video)
GOOGLE_API_TIMEOUT_SECONDS = 600
GOOGLE_API_TIMEOUT_MS = GOOGLE_API_TIMEOUT_SECONDS * 1000

_INLINE_CREDENTIAL_DIRECTORY: str | None = None
_INLINE_CREDENTIAL_PATH: str | None = None
_INLINE_CREDENTIAL_PREVIOUS_PATH: str | None = None
_INLINE_CREDENTIAL_PREVIOUS_SIGTERM: Any = None


def _inline_service_account_info() -> dict[str, Any] | None:
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(info, dict) or info.get("type") != "service_account":
        return None
    required = ("project_id", "private_key", "client_email", "token_uri")
    if any(not isinstance(info.get(name), str) or not info[name].strip() for name in required):
        return None
    return info


def _install_inline_service_account_file() -> str | None:
    """Materialize an encrypted Studio credential privately inside this job worker."""
    global _INLINE_CREDENTIAL_DIRECTORY, _INLINE_CREDENTIAL_PATH, _INLINE_CREDENTIAL_PREVIOUS_PATH
    global _INLINE_CREDENTIAL_PREVIOUS_SIGTERM
    if _INLINE_CREDENTIAL_PATH and os.path.isfile(_INLINE_CREDENTIAL_PATH):
        return _INLINE_CREDENTIAL_PATH
    info = _inline_service_account_info()
    if info is None:
        return None
    directory = tempfile.mkdtemp(prefix="openmontage-google-")
    os.chmod(directory, 0o700)
    path = os.path.join(directory, "service-account.json")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(info, handle, separators=(",", ":"))
    _INLINE_CREDENTIAL_DIRECTORY = directory
    _INLINE_CREDENTIAL_PATH = path
    _INLINE_CREDENTIAL_PREVIOUS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path

    def cleanup() -> None:
        global _INLINE_CREDENTIAL_DIRECTORY, _INLINE_CREDENTIAL_PATH
        global _INLINE_CREDENTIAL_PREVIOUS_SIGTERM
        if _INLINE_CREDENTIAL_PREVIOUS_PATH is None:
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        else:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _INLINE_CREDENTIAL_PREVIOUS_PATH
        if _INLINE_CREDENTIAL_PATH:
            try:
                os.unlink(_INLINE_CREDENTIAL_PATH)
            except FileNotFoundError:
                pass
        if _INLINE_CREDENTIAL_DIRECTORY:
            try:
                os.rmdir(_INLINE_CREDENTIAL_DIRECTORY)
            except OSError:
                pass
        _INLINE_CREDENTIAL_DIRECTORY = None
        _INLINE_CREDENTIAL_PATH = None
        if _INLINE_CREDENTIAL_PREVIOUS_SIGTERM is not None:
            signal.signal(signal.SIGTERM, _INLINE_CREDENTIAL_PREVIOUS_SIGTERM)
            _INLINE_CREDENTIAL_PREVIOUS_SIGTERM = None

    def cleanup_on_termination(signum: int, frame: Any) -> None:
        cleanup()
        raise SystemExit(128 + signum)

    _INLINE_CREDENTIAL_PREVIOUS_SIGTERM = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, cleanup_on_termination)
    atexit.register(cleanup)
    return path


def service_account_configured() -> bool:
    """True when a service-account key file or inline Studio secret is available."""
    if _inline_service_account_info() is not None:
        return True
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    return bool(path and os.path.exists(path))


def has_google_credentials() -> bool:
    """True when GOOGLE_API_KEY, GEMINI_API_KEY, or service account is configured."""
    return bool(
        os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or service_account_configured()
    )


def get_genai_client(
    http_options: Any | None = None,
    location: str | None = None,
    force_vertex: bool = False,
) -> Any:
    """Initialize Google GenAI using the configured credential mode.

    ``location`` overrides the Vertex region for globally hosted models. It is
    deliberately ignored by the API-key backend, which has no region setting.
    """
    from google import genai

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in (
        "true",
        "1",
    ) or os.environ.get("GOOGLE_GENAI_USE_ENTERPRISE", "").lower() in ("true", "1")

    if force_vertex or use_vertex or (not api_key and service_account_configured()):
        inline_info = _inline_service_account_info()
        if inline_info is not None:
            _install_inline_service_account_file()
        kwargs = {
            "vertexai": True,
            "location": resolve_google_location(location),
            "http_options": http_options,
        }
        project_id = resolve_project_id()
        if project_id:
            kwargs["project"] = project_id
        return genai.Client(**kwargs)
    else:
        if api_key:
            return genai.Client(api_key=api_key, http_options=http_options)
        return genai.Client(http_options=http_options)


def resolve_project_id(creds_project_id: str | None = None) -> str | None:
    """Resolve the GCP project id from env vars, falling back to the key file's.

    Vertex AI needs an explicit project id; TTS does not. We prefer an explicit
    env override so users can target a project other than the key's own.
    """
    info = _inline_service_account_info()
    return (
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
        or os.environ.get("GCLOUD_PROJECT")
        or creds_project_id
        or (info.get("project_id") if info else None)
    )


def get_access_token(scopes: list[str] | None = None) -> tuple[str, str | None]:
    """Mint an OAuth access token from the service-account JSON.

    Returns ``(access_token, project_id)``. ``project_id`` is the one embedded
    in the key file (callers should still prefer :func:`resolve_project_id`).

    Raises:
        RuntimeError: if ``google-auth`` is missing or the credentials cannot
            be loaded/refreshed — with a message the agent can surface verbatim.
    """
    if scopes is None:
        scopes = [CLOUD_PLATFORM_SCOPE]

    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "Service-account auth requires the 'google-auth' package. "
            "Install it with: pip install google-auth"
        ) from exc

    inline_info = _inline_service_account_info()
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if inline_info is None and (not path or not os.path.exists(path)):
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS is not set or points to a missing "
            "file; cannot use service-account authentication."
        )

    try:
        creds = (
            service_account.Credentials.from_service_account_info(inline_info, scopes=scopes)
            if inline_info is not None
            else service_account.Credentials.from_service_account_file(path, scopes=scopes)
        )
        creds.refresh(Request())
    except Exception as exc:  # noqa: BLE001 - re-raised as actionable message
        raise RuntimeError(
            f"Failed to load/refresh service-account credentials from {path}: {exc}"
        ) from exc

    token = creds.token
    if not token or not isinstance(token, str):
        raise RuntimeError(
            "Service-account credentials did not yield a valid access token."
        )

    project_id = getattr(creds, "project_id", None)
    ret_project_id = str(project_id) if project_id is not None else None
    return token, ret_project_id
