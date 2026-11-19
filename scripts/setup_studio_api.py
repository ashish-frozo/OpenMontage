#!/usr/bin/env python3
"""Create a private Studio REST worker config and install its launchd agent."""
from __future__ import annotations

import base64
import getpass
import json
import os
from pathlib import Path
import plistlib
import secrets
import subprocess
import sys


LABEL = "ai.openmontage.studio-api"
SUPABASE_URL = "https://gmqhfqvaspwvxzcviibm.supabase.co"
PUBLIC_ORIGIN = "https://ashishs-mac-mini.tail438c99.ts.net:10000"


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    home = Path.home()
    config_dir = home / ".config/openmontage-studio"
    config_path = config_dir / "worker.json"
    agent_path = home / "Library/LaunchAgents" / f"{LABEL}.plist"
    data_dir = home / ".local/share/openmontage-studio"
    log_dir = home / "Library/Logs/openmontage-studio"
    python = repo / ".venv/bin/python"

    if sys.platform != "darwin":
        raise SystemExit("This installer configures a macOS launchd agent.")
    if not python.is_file():
        raise SystemExit(f"Project virtualenv not found: {python}")
    if config_path.exists() or agent_path.exists():
        raise SystemExit("Studio API config or launch agent already exists; refusing to overwrite it.")

    supabase_key = getpass.getpass("Supabase project secret key (input hidden): ").strip()
    if not supabase_key or len(supabase_key) > 4096:
        raise SystemExit("A valid Supabase secret key is required.")
    encryption_key = getpass.getpass("Vercel STUDIO_CREDENTIAL_ENCRYPTION_KEY (input hidden): ").strip()
    try:
        decoded = base64.b64decode(encryption_key, validate=True)
    except Exception as exc:
        raise SystemExit("The credential encryption key must be valid base64.") from exc
    if len(decoded) != 32 or base64.b64encode(decoded).decode() != encryption_key:
        raise SystemExit("The credential encryption key must be canonical base64 for exactly 32 bytes.")

    for directory in (config_dir, data_dir, data_dir / "projects", log_dir, agent_path.parent):
        directory.mkdir(parents=True, exist_ok=True)
    config = {
        "supabase_url": SUPABASE_URL,
        "supabase_secret_key": supabase_key,
        "base_url": PUBLIC_ORIGIN,
        "media_signing_secret": secrets.token_urlsafe(48),
        "credential_encryption_key": encryption_key,
        "projects_dir": str(data_dir / "projects"),
        "openshorts_api_url": "http://127.0.0.1:8017",
        "host": "127.0.0.1",
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    config_path.chmod(0o600)
    agent = {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-m", "content_factory.studio_api", "--config", str(config_path), "--port", "8770"],
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        "StandardOutPath": str(log_dir / "worker.log"),
        "StandardErrorPath": str(log_dir / "worker.error.log"),
    }
    with agent_path.open("wb") as stream:
        plistlib.dump(agent, stream)
    agent_path.chmod(0o600)
    uid = os.getuid()
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(agent_path)], check=True)
    print("Studio API launch agent installed. Local API port: 8770.")
    print(f"Private config: {config_path}")
    print("The existing MCP listeners and Tailscale routes were not changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
