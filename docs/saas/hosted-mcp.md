# Workspace hosted MCP

`content_factory.hosted` runs the existing OpenMontage MCP behind Studio-issued
workspace bearer tokens. The existing GitHub owner-only remote mode in
`content_factory.remote` remains unchanged for private/self-hosted deployments.

## Request path

1. Studio creates a random `om_live_…` token for an owner/admin. Supabase stores
   only its SHA-256 hash, workspace, scopes, expiry, creator, and revocation
   state. The owner chooses read-only access or production access; the plaintext
   is returned once to the browser for copying.
2. FastMCP hashes the incoming bearer value and resolves it through the
   service-role-only `resolve_workspace_mcp_token` RPC. The RPC rejects expired
   or revoked tokens and tokens whose creator is no longer a workspace
   owner/admin/producer.
3. Middleware checks every `project_id` against
   `authorize_workspace_project(workspace_id, project_id)` before a tool runs.
   It also checks the registered tool's `readOnlyHint`: a read-only token can
   call read-only tools, while tools that change state require `mcp:write`.
   Unknown tools fail closed for read-only tokens.
4. The existing `Factory` is directed to `<projects_dir>/<workspace_uuid>/`.
   SQLite plans, checkpoints, artifacts, and local workers remain separated by
   workspace while retaining the current pipeline validation and approval
   behavior.
5. `studio_projects` and `studio_project_brief` expose the signed-in workspace's
   Studio briefs to a connected MCP client. Other project tools require a
   project UUID from that workspace.
6. `factory_checkpoint` writes the canonical local checkpoint, then mirrors its
   stage, checkpoint status, and `awaiting_human` approval state to the matching
   Supabase project through a service-role-only RPC. Studio reads those fields
   under the same workspace RLS policy and prioritizes pending approvals.

## Run on a persistent worker host

This service is stateful and needs a persistent volume. It is not a Vercel
function. Configure a JSON file with mode `0600`:

```json
{
  "supabase_url": "https://your-project.supabase.co",
  "service_role_key": "server-only-key",
  "base_url": "https://mcp.your-domain.example",
  "media_signing_secret": "replace-with-output-of-openssl-rand-hex-32",
  "projects_dir": "/var/lib/openmontage/projects",
  "host": "0.0.0.0",
  "path": "/mcp"
}
```

Apply the migrations in `supabase/migrations/` in filename order, then install
`requirements-mcp-remote.txt` and start:

```sh
python -m content_factory.hosted --config /etc/openmontage/studio-mcp.json --port 8769
```

Configure the same canonical base64 `STUDIO_CREDENTIAL_ENCRYPTION_KEY` on the
Studio server and MCP host. At job submission, the host resolves the selected
registry tool's credential contract, fetches that workspace's active encrypted
provider credential, decrypts it in memory, and passes it only to that worker
subprocess. Selectors receive credentials only for connected candidate
providers in that selector's capability. Managed provider variables inherited
by the host are removed from the worker unless supplied by its workspace. The
Studio encryption key, Supabase service credentials, and other host environment
secrets are removed before launch. Credentials are not stored in job records
or logs. The Studio provider ID must
match the provider ID reported by the selected tool. A simple API key is enough
for single-value tools; for tools that need multiple values, save one-line JSON
such as `{"HIGGSFIELD_API_KEY":"…","HIGGSFIELD_API_SECRET":"…"}`. The tool
contract rejects environment names it did not declare.
For Google Cloud, save a service-account JSON key under provider ID `google`;
Google-backed tools use that workspace credential when no provider-specific
credential is saved. The host passes the JSON only to the selected worker. If
Google's SDK requires Application Default Credentials, the worker writes it to
a private temporary directory (0700 directory, 0600 file) and removes it on
normal exit or job cancellation.

Generate `media_signing_secret` once with `openssl rand -hex 32` and keep it
stable across restarts. Rotating it invalidates existing media links.

Set `NEXT_PUBLIC_MCP_ENDPOINT` in Studio to the public HTTPS `/mcp` URL. Configure
the service role key only on the MCP host and Studio server; never expose it as
a `NEXT_PUBLIC_*` variable. Put TLS and request size/time limits at the reverse
proxy. Keep the volume private to this worker host.

Studio owners and admins can use this configured endpoint to create a private
engine connection. Studio generates a workspace token, stores only its hash in
the token table and its AES-GCM ciphertext in `engine_secrets`, then performs an
authenticated Streamable HTTP MCP handshake and snapshots the server's tool
catalog. Internal Studio engine tokens are hidden from the copy-once token list;
revoking one through the database also revokes its engine connection and erases
its encrypted bearer value. The configured endpoint is deployment-controlled;
Studio does not accept arbitrary per-workspace server URLs.

MCP clients must send the copied token as `Authorization: Bearer <token>`. The
service does not yet provide a browser OAuth authorization flow. Output media
is copied to the private `studio-media` Supabase Storage bucket after successful
hosted jobs using resumable uploads (6 MB chunks), with a service-role-only
workspace/project media index. Apply
`202611210002_studio_private_media.sql` after the control-plane and durable-job
migrations. Media can be downloaded through a signed, workspace-and-project-bound
MCP URL that expires within five minutes, or transferred using
`factory_export_media` in bounded byte chunks. The MCP URL rechecks project
ownership, serves from the private persistent volume when available, and falls
back to a five-minute Supabase signed URL when the local copy is absent. The
service-role key is never returned to clients. A transient replication failure
leaves the job result marked `media_storage.status=pending_retry`; a later
successful job re-syncs the project's media. Protect the endpoint with HTTPS
and reverse-proxy rate limits. Hosted submissions use Supabase as
the durable queue and lifecycle authority. The enqueue RPC validates producer
membership, project ownership, idempotency, entitlement limits, per-project
concurrency, and estimated spend reservations. The FastMCP server lifespan
starts the worker pool when the process starts and stops it with the process.
Each worker claims a leased job and runs it through the existing local SQLite
execution adapter on the persistent project volume. Set
`STUDIO_WORKER_CONCURRENCY` (1–32, default 2) to control workers in this host
process; the database enforces the per-project concurrency limit. On shutdown
or lease expiry, uncertain work moves to `reconciling` and is never
automatically retried, because a provider may still finish or bill. Self-hosted
stdio mode continues to use the local SQLite queue. Fine-grained operation
progress and multiple isolated execution replicas are not yet implemented.

## Security boundaries and remaining work

- Studio shows the token once; the token table has no authenticated-user RLS
  reads. Only service-role RPCs can create, resolve, or revoke one.
- Read-only tokens cannot call tools marked as writing; production tokens carry
  both `mcp:read` and `mcp:write`. Tool annotation metadata is loaded from the
  registered FastMCP catalog, not a manually maintained name allowlist.
- The creator must still be a workspace member with production permissions;
  creator removal/demotion makes their token invalid on its next request.
- A tool call with a foreign/missing Studio project ID is denied before the
  filesystem-backed `Factory` runs.
- Workspace folders use mode `0700`. The MCP host remains trusted to isolate
  customer workers; process/container sandboxing per workspace is still needed
  before accepting hostile multi-tenant workloads.
- Supabase is authoritative for hosted job lifecycle; SQLite is the execution
  adapter and self-hosted queue. A host outage leaves unclaimed jobs queued and
  reconciles leased jobs without automatically retrying uncertain work.
- Media is stored in a private Supabase bucket, and the object index is service-role-only.
- If a storage outage overlaps a completed render, the render remains succeeded
  and its result reports pending media replication; keep the worker volume until
  storage is available and a later successful job triggers a project re-sync.
