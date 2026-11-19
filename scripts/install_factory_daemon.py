"""Run once with sudo on macOS; services execute as the invoking user."""
import os
import plistlib
import pwd
import subprocess
from pathlib import Path


def main():
    if os.geteuid() != 0 or not os.environ.get("SUDO_USER"):
        raise SystemExit("Run with sudo from your normal account")
    user = pwd.getpwnam(os.environ["SUDO_USER"])
    root = Path(__file__).resolve().parents[1]
    home = Path(user.pw_dir)
    config = home / ".config/content-factory/remote.json"
    if not config.is_file():
        raise SystemExit("Run scripts/configure_factory_remote.py first")
    logs = home / "Library/Logs/ContentFactory"
    logs.mkdir(parents=True, exist_ok=True)
    os.chown(logs, user.pw_uid, user.pw_gid)
    label = "ai.frozo.content-factory"
    target = Path("/Library/LaunchDaemons") / (label + ".plist")
    data = {
        "Label": label, "UserName": user.pw_name,
        "ProgramArguments": [str(root / ".venv/bin/python"), "-m", "content_factory.remote", "--config", str(config)],
        "WorkingDirectory": str(root), "RunAtLoad": True, "KeepAlive": True,
        "ThrottleInterval": 30, "Umask": 63,
        "EnvironmentVariables": {"HOME": str(home), "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", "LEMO_OPUSCAR_HOME": str(home / "lemo-opuscar")},
        "StandardOutPath": str(logs / "server.log"), "StandardErrorPath": str(logs / "server-error.log"),
    }
    target.write_bytes(plistlib.dumps(data))
    target.chmod(0o644)
    subprocess.run(["launchctl", "bootout", "system/" + label], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", "system", str(target)], check=True)
    print("Installed boot service:", label)


if __name__ == "__main__":
    main()
