# OpenMontage Studio REST API

Studio uses its first-party HTTP API for video workflows. The self-hostable
OpenMontage MCP remains a separate interface for external AI clients.

## Request model

- Next.js server actions on Vercel call the worker directly at the server-only
  `STUDIO_WORKER_API_URL` origin.
- Each request uses the signed-in Supabase user's access token as a bearer token.
- The worker validates that token with Supabase Auth, checks current workspace
  membership and role, and verifies project ownership before invoking an
  operation.
- `POST /v1/operations/{operation}` accepts `{ "workspace_id": "…",
  "arguments": { … } }` and returns `{ "result": … }`.
- `GET /healthz` is a minimal health check. It reveals no configuration.
- Long-running work is queued in the durable Supabase jobs table. The worker
  owns the lease and runs the existing local production code.
- Five-minute media links use `GET /download/{ticket}` and re-check workspace
  project access before serving or redirecting to private object storage.

## Mac mini configuration

Install the worker on the Mac mini with the interactive installer:

```bash
cd ~/WORK/openmontage/OpenMontage
.venv/bin/python scripts/setup_studio_api.py
```

It prompts without echo for the Supabase project secret key and the exact
`STUDIO_CREDENTIAL_ENCRYPTION_KEY` already configured in Vercel, creates a
mode-0600 JSON config and launchd agent, and starts the REST API on loopback
port 8770. It does not edit the existing MCP launch agents or Tailscale routes.
The service config stores the API secret and encryption key locally with
owner-only permissions; never commit or share that file.

The installer defaults `OPENSHORTS_API_URL` to the local OpenShorts service at
`127.0.0.1:8017`. Change the value only if that service moves. Move Tailscale's
Funnel route on port 10000 to port 8770 only after the new worker reports
healthy; keep the main MCP endpoint on port 443 separate.

For a manual deployment, create a private config file with mode `0600`:

```json
{
  "supabase_url": "https://gmqhfqvaspwvxzcviibm.supabase.co",
  "supabase_secret_key": "server-only-key",
  "base_url": "https://ashishs-mac-mini.tail438c99.ts.net:10000",
  "media_signing_secret": "stable-random-64-hex-characters",
  "credential_encryption_key": "existing-Vercel-encryption-key",
  "projects_dir": "/Users/your-user/Library/Application Support/OpenMontage/studio-projects",
  "openshorts_api_url": "http://127.0.0.1:8017",
  "host": "127.0.0.1"
}
```

The worker reads the credential encryption key from this protected config at
startup. It must match the key used by Studio to encrypt provider keys. Keep
the existing owner-only MCP process and its port 443 route unchanged.

Start the API worker with:

```sh
python -m content_factory.studio_api --config ~/.config/openmontage/studio-api.json --port 8770
```

After local `GET http://127.0.0.1:8770/healthz` returns the expected service
name and version, expose it through the dedicated Funnel port and set the
Vercel server-only `STUDIO_WORKER_API_URL` to the HTTPS origin. The main MCP
origin remains a separate endpoint.

## Vercel configuration

Set `STUDIO_WORKER_API_URL` as a server-only variable with value
`https://your-machine.ts.net:10000`. Set `SUPABASE_SECRET_KEY` as a server-only
secret for Studio's protected credential-management operations. Keep
`NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` public.
Never use a `NEXT_PUBLIC_` prefix for secret keys or the credential-encryption
key.
