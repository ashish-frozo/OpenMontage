#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
if [ ! -f "$HOME/.config/content-factory/remote.json" ]; then
  .venv/bin/python scripts/configure_factory_remote.py
fi
.venv/bin/python -c 'from pathlib import Path; from content_factory.remote import load_config; load_config(Path.home() / ".config/content-factory/remote.json")'
sudo .venv/bin/python scripts/install_factory_daemon.py
echo 'Boot service installed. Checking authentication before enabling HTTPS...'
ready=0
for attempt in {1..30}; do
  status=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8768/mcp || true)
  if [ "$status" = 401 ]; then ready=1; break; fi
  sleep 1
done
if [ "$ready" != 1 ]; then
  echo 'Server did not return the required 401. Check ~/Library/Logs/ContentFactory/server-error.log; HTTPS has not been enabled.'
  exit 1
fi
/Applications/Tailscale.app/Contents/MacOS/Tailscale funnel --bg --https=443 http://127.0.0.1:8768
echo 'MCP URL: https://ashishs-mac-mini.tail438c99.ts.net/mcp'
