"""Private, single-owner HTTPS deployment behind a loopback reverse proxy."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth import AccessToken
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse

from content_factory.server import build_server
from content_factory.service import Factory, identifier


class DownloadSigner:
    """Issue scoped, expiring bearer URLs without exposing a folder listing."""

    def __init__(self, origin: str, secret: str):
        self.origin = origin.rstrip("/")
        self.key = hmac.new(secret.encode(), b"content-factory-download-v1", hashlib.sha256).digest()

    def media_path(self, factory, project_id, relative_path):
        from content_factory.media import media_path
        return media_path(factory, project_id, relative_path)

    def sign(self, project_id, relative_path, ttl_seconds=300):
        payload = json.dumps({"p": project_id, "f": relative_path, "exp": int(time.time()) + min(3600, max(1, ttl_seconds))}, separators=(",", ":")).encode()
        signature = hmac.new(self.key, payload, hashlib.sha256).digest()
        ticket = base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")
        return f"{self.origin}/download/{ticket}"

    def verify(self, factory, ticket):
        try:
            if len(ticket) > 2048:
                return None
            raw = base64.b64decode(ticket + "=" * (-len(ticket) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(raw).decode().rstrip("=") != ticket:
                return None
            payload, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(hmac.new(self.key, payload, hashlib.sha256).digest(), signature):
                return None
            data = json.loads(payload)
            if int(data["exp"]) < time.time():
                return None
            return self.media_path(factory, data["p"], data["f"])
        except (ValueError, KeyError, TypeError, OSError):
            return None


class AuthDiagnostics:
    """Log connection stages without tokens, cookies, bodies or URL queries."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        agent = headers.get(b"user-agent", b"").lower()
        client = next((name for name in ("chatgpt", "openai", "claude", "codex", "python", "curl") if name.encode() in agent), "other")

        async def report(message):
            if message["type"] == "http.response.start":
                logging.getLogger("content_factory.auth").warning(
                    "MCP request method=%s path=%s client=%s auth_present=%s status=%s",
                    scope["method"], "/download/[redacted]" if scope["path"].startswith("/download/") else scope["path"], client,
                    b"authorization" in headers, message["status"],
                )
            await send(message)
        await self.app(scope, receive, report)


class OwnerGitHubProvider(GitHubProvider):
    """Accept a revocable Harness key or an owner-verified GitHub OAuth token."""

    def __init__(self, *, allowed_user_ids, harness_api_key=None, **kwargs):
        configured_user_ids = [str(value) for value in allowed_user_ids]
        self.allowed_user_ids = frozenset(configured_user_ids)
        if not self.allowed_user_ids or not all(value.isdecimal() for value in self.allowed_user_ids):
            raise ValueError("At least one numeric GitHub user ID is required")
        self.harness_api_subject = configured_user_ids[0]
        self.harness_api_key = harness_api_key
        super().__init__(**kwargs)

    async def load_access_token(self, token):
        if self.harness_api_key and hmac.compare_digest(token, self.harness_api_key):
            subject = self.harness_api_subject
            return AccessToken(
                token=token,
                client_id="content-factory-harness-api-key",
                scopes=["read:user"],
                subject=subject,
                claims={"sub": subject, "auth_method": "api_key"},
            )
        verified = await super().load_access_token(token)
        if verified is None or str(verified.claims.get("sub", "")) not in self.allowed_user_ids:
            return None
        return verified


def load_config(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Configuration must be a regular file")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("Configuration contains credentials; set permissions to 600")
    config = json.loads(path.read_text())
    parsed = urlsplit(config["base_url"])
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("base_url must be an HTTPS origin")
    for key in ("client_id", "client_secret"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"Missing {key}")
    api_key = config.get("harness_api_key")
    if api_key is not None and (not isinstance(api_key, str) or len(api_key) < 32):
        raise ValueError("harness_api_key must be at least 32 characters when configured")
    return config


def build_remote(config, factory=None):
    factory = factory or Factory()
    signer = DownloadSigner(config["base_url"], config["client_secret"])
    auth = OwnerGitHubProvider(
        client_id=config["client_id"], client_secret=config["client_secret"],
        base_url=config["base_url"].rstrip("/"),
        allowed_user_ids=config["allowed_user_ids"],
        harness_api_key=config.get("harness_api_key"),
        required_scopes=["read:user"],
        require_authorization_consent=True,
        fastmcp_access_token_expiry_seconds=3600,
    )
    server = build_server(factory, server_class=FastMCP, server_options={"auth": auth}, download_signer=signer)

    @server.custom_route("/download/{ticket}", methods=["GET"], include_in_schema=False)
    async def download(request: Request):
        path = signer.verify(factory, request.path_params["ticket"])
        if path is None:
            return PlainTextResponse("Link expired or invalid", status_code=404)
        return FileResponse(path, filename=path.name, content_disposition_type="inline",
                            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})

    return server


def main():
    parser = argparse.ArgumentParser(description="GitHub-authenticated Content Factory MCP")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    # Renderer dependencies must be visible even when this MCP is started by
    # an app launcher with a minimal PATH instead of an interactive shell.
    if os.sys.platform == "darwin":
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        for node_bin in (
            Path("/opt/homebrew/opt/node@22/bin"),
            Path("/usr/local/opt/node@22/bin"),
        ):
            if (node_bin / "node").is_file() and str(node_bin) not in path_entries:
                path_entries.insert(0, str(node_bin))
                break
        os.environ["PATH"] = os.pathsep.join(filter(None, path_entries))
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if chrome.is_file():
            os.environ.setdefault("PLAYWRIGHT_CHROME", str(chrome))
        lemo_home = Path.home() / "lemo-opuscar"
        if lemo_home.is_dir():
            os.environ.setdefault("LEMO_OPUSCAR_HOME", str(lemo_home))
    os.umask(0o077)
    config = load_config(args.config)
    build_remote(config).run(transport="http", host="127.0.0.1", port=args.port, path="/mcp",
                             middleware=[Middleware(AuthDiagnostics)], uvicorn_config={"access_log": False})


if __name__ == "__main__":
    main()
