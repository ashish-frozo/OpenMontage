# Mac mini deployment: ChatGPT.com and Claude.ai

The server runs on the Mac mini. Both websites use the same Streamable HTTP MCP
endpoint, with GitHub OAuth and an allowlist of immutable GitHub user IDs.
FastMCP's OAuth proxy handles MCP client registration, consent, PKCE, encrypted
credential persistence and token validation. GitHub sign-in alone does not grant
access: `OwnerGitHubProvider` also checks the configured user IDs on every request.
The local stdio entry point remains available without web authentication.

## Current deployment

- Repository: `/Users/ashishdhiman/WORK/openmontage/OpenMontage`
- Intended endpoint: `https://ashishs-mac-mini.tail438c99.ts.net/mcp`
- GitHub OAuth callback: `https://ashishs-mac-mini.tail438c99.ts.net/auth/callback`
- Allowed owner ID: `214779977` (`ashish-frozo`)
- Local listener: `127.0.0.1:8768`
- Credentials: `~/.config/content-factory/remote.json`, mode 600, outside Git
- Service: `/Library/LaunchDaemons/ai.frozo.content-factory.plist`
- Logs: `~/Library/Logs/ContentFactory/`

Tailscale Funnel makes the HTTPS address internet-reachable; OAuth keeps the MCP
tools private. The former private service on 443 was moved to private port 9443 with user approval. The service on 8443 is unchanged. Port 443 now forwards only to Content Factory.
Do not forward an unauthenticated stdio-to-HTTP bridge to the internet.

## Install

Install core requirements and `requirements-mcp-remote.txt` into the server's own
Python environment. Do not copy a virtualenv from another computer.

Create a GitHub OAuth App with the homepage set to the HTTPS origin above and the
callback set exactly as shown. Only the `read:user` scope is requested; repository
access is unnecessary. Then run from the client terminal:

```sh
ssh -t macmini 'cd ~/WORK/openmontage/OpenMontage && bash scripts/setup_factory_mac.sh'
```

Enter the client ID and secret at the prompts. The secret input is hidden. The
installer asks for the Mac mini administrator password through `sudo`, installs
a system LaunchDaemon running as the normal user, checks that anonymous MCP
requests receive 401, and only then enables Funnel on port 443. If Funnel needs
tailnet approval, follow its authorization link and rerun the installer.

The daemon uses RunAtLoad and KeepAlive, with a 30-second restart throttle. It can
start before graphical login because it is a system daemon, not a LaunchAgent.
Tailscale must also be configured for unattended startup. Check its behavior after
a planned reboot; do not claim reboot verification from merely installing a plist.
FileVault unlock, device sleep, loss of connectivity and Tailscale key expiry can
still prevent remote access. This install does not change those security settings.

## Verify

```sh
sudo launchctl print system/ai.frozo.content-factory
curl -i https://ashishs-mac-mini.tail438c99.ts.net/mcp
```

An anonymous request should receive 401 and a WWW-Authenticate metadata challenge.
OAuth metadata must be reachable without authentication. In each website, add a
custom remote MCP connector with the endpoint above, select OAuth where offered,
and sign in as the allowed GitHub owner. Verify discovery and call `factory_plugins`
before submitting production jobs. Account/workspace feature policies still apply.

Job supervisors persist independently of web sessions. A machine reboot interrupts
active rendering; use `factory_reconcile_job` to record an interrupted job and review
it before resubmitting. Startup does not automatically repeat paid generation.

Tools currently return server-local output paths. A website connector does not by
itself make rendered files downloadable; retrieve outputs through SSH/Screen
Sharing until a separately authenticated artifact delivery mechanism is added.

## Copy policy

The source tree, instructions, project workspaces and generated assets were copied
without deleting destination-only files. Changed destination files were backed up
under `~/WORK/openmontage/pre-factory-sync-backup`. Existing Git history and local
dependency installs were retained. `.env*`, Python virtualenvs, `node_modules` and
generated Python/test caches were excluded. Configure provider credentials on the
server separately; copied source is not evidence that every paid provider is ready.

## Maintenance

Keep the OAuth state directory and client secret stable across restarts. Changing
the secret can require reconnecting clients. Monitor and rotate service logs, and
monitor free disk space before rendering. To stop the service:

```sh
sudo launchctl bootout system/ai.frozo.content-factory
/Applications/Tailscale.app/Contents/MacOS/Tailscale funnel --https=443 off
```

References: [FastMCP GitHub OAuth](https://gofastmcp.com/integrations/github),
[Tailscale Funnel](https://tailscale.com/kb/1223/funnel),
[ChatGPT custom MCP](https://developers.openai.com/api/docs/guides/custom-mcp-server),
[Claude custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).

## Browser downloads

Call `factory_outputs` to find a render, then call `factory_download_url` with its
project ID and path relative to that project (for example,
`renders/final_ident_5s_vertical.mp4`). The tool returns an HTTPS link valid for
five minutes. Open it in a browser to save the file. Anyone holding the link can
use it until expiry, so do not share it publicly. Only media under `renders/` or
`assets/` can be downloaded; paths outside the project and altered tickets fail.
