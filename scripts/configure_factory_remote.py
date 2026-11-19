"""Interactive credential entry on the server; never supply secrets in arguments."""
import getpass
import json
import os
from pathlib import Path


def main():
    os.umask(0o077)
    path = Path.home() / ".config/content-factory/remote.json"
    if path.exists():
        raise SystemExit(f"Configuration already exists at {path}; edit it intentionally to rotate credentials")
    default_origin = "https://ashishs-mac-mini.tail438c99.ts.net"
    origin = (input(f"Public HTTPS origin [{default_origin}]: ").strip() or default_origin).rstrip("/")
    user_ids = (input("Allowed GitHub user IDs [214779977 = ashish-frozo]: ").strip() or "214779977").split(",")
    client_id = input("GitHub OAuth app client ID: ").strip()
    secret = getpass.getpass("GitHub OAuth app client secret (hidden): ").strip()
    harness_key = getpass.getpass("Optional long-lived Harness API key (hidden; leave blank to disable): ").strip()
    if not origin.startswith("https://") or not all(x.strip().isdecimal() for x in user_ids) or not client_id or not secret:
        raise SystemExit("Invalid or missing configuration")
    if harness_key and len(harness_key) < 32:
        raise SystemExit("Harness API key must be at least 32 characters")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x") as output:
        config = dict(base_url=origin, allowed_user_ids=[x.strip() for x in user_ids], client_id=client_id, client_secret=secret)
        if harness_key:
            config["harness_api_key"] = harness_key
        json.dump(config, output)
    print(f"Saved private configuration to {path}")


if __name__ == "__main__":
    main()
