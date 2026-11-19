# OpenMontage Studio

Hosted Studio is a Next.js App Router application intended for deployment from
this directory as the Vercel project root. It uses Supabase Auth with
cookie-backed server sessions, Postgres RLS for workspace and project access,
and server actions for sign-in, workspace setup, and brief creation.

## Local setup

1. Create a dedicated Supabase project and apply the migrations in
   `../../supabase/migrations/` in filename order. The Studio schema starts with
   `202611180001_saas_control_plane.sql` and adds the reusable workspace brand
   profile in `202611190001_workspace_brand_profiles.sql`, and encrypted
   workspace engine connections in `202611200001_studio_engine_connections.sql`.
2. Copy `.env.example` to `.env.local` and set the Supabase project URL, its
   browser-safe publishable key, and the local site URL. Configure the
   server-only `SUPABASE_SERVICE_ROLE_KEY` and generate
   `STUDIO_CREDENTIAL_ENCRYPTION_KEY` with `openssl rand -base64 32` before
   connecting an MCP engine or enabling provider credential storage.
3. Allow `http://localhost:3000/auth/callback` in the Supabase Auth redirect
   URLs, then run `npm install` and `npm run dev` here.
4. For Vercel, set this folder as the project root. Add the same Supabase URL
   and publishable key plus `NEXT_PUBLIC_SITE_URL` for the production domain.
   Add the production `/auth/callback` URL to Supabase's Auth redirect allowlist.

Only Supabase's publishable key belongs in the browser. Do not add a service
role key, provider API key, or encryption key to `NEXT_PUBLIC_*` variables.
Set the service-role key and credential encryption key as protected server
environment variables in Vercel. Back up the encryption key securely: losing it
will make saved provider credentials unreadable. Rotating it requires an
explicit credential re-encryption migration; do not replace it in production
without one. The persistent hosted MCP worker must receive the same encryption
key as a protected server environment variable so it can hand credentials to
the selected job only.

## Current product boundary

The app signs creators in with email links, creates a workspace, saves video
briefs as tenant-scoped project rows, and displays RLS-scoped production
activity with lease-bound progress. Workspace owners and admins can create
revocable, 90-day workspace MCP tokens; Studio stores only their hashes. See
`../../docs/saas/hosted-mcp.md` for the companion persistent-volume MCP host.
Owners and admins can
store provider credentials; Studio encrypts them with AES-256-GCM before calling
a service-role-only transactional RPC. Plaintext keys are not stored, queried
back into the UI, or written to audit events. Owners and admins can revoke a
key, which removes its encrypted payload and records an audit event in one
transaction. Owners and admins can connect Studio to its deployment-configured
OpenMontage MCP endpoint; Studio stores a private workspace token encrypted
server-side and snapshots the server's tool catalog. From an evergreen brief,
an authorized creator can explicitly start a free, five-result Wikipedia
research step after MCP availability and $0.00 preflight checks. The saved route
is submitted with an idempotency key and the click recorded as approval evidence;
job progress appears in the workspace activity list. A member can open completed
results to review up to five safe HTTPS links and snippets. Search snippets are
source leads and are not represented as verified evidence. Live/current
research, source retrieval and claim verification, script approvals, and social
publishing are not yet available in Studio. From any project row, Studio can
request a short lived signed preview/download link for an existing render from
the configured MCP host. Durable object-storage delivery
and project stage-status synchronization are still pending. Local production
continues to use the self-hosted runner.
