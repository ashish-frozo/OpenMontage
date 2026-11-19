"""Set or rotate the private Harness API key without echoing it."""
import getpass
import json
import os
import tempfile
from pathlib import Path


def main():
    os.umask(0o077)
    path = Path.home() / ".config/content-factory/remote.json"
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"Private remote config not found: {path}")
    if path.stat().st_mode & 0o077:
        raise SystemExit("Remote config permissions must be 600")
    key = getpass.getpass("New Harness API key (hidden): ").strip()
    if len(key) < 32:
        raise SystemExit("Use a randomly generated key with at least 32 characters")
    config = json.loads(path.read_text())
    config["harness_api_key"] = key
    fd, temp_name = tempfile.mkstemp(prefix="remote.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(config, output)
            output.write("\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    print("Harness API key saved. Restart the Content Factory service to activate it.")


if __name__ == "__main__":
    main()
