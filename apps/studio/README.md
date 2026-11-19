# OpenMontage Studio

Studio is the hosted Next.js app. Supabase handles sign-in, workspace data,
projects, provider credentials, and durable job records. The app's server
actions call a separate REST worker for research and video operations. The
open-source OpenMontage MCP is a separate product and is not a Studio runtime
dependency.

## Local setup

1. Create a Supabase project and apply the migrations in
   `../../supabase/migrations/` in filename order.
2. Copy `.env.example` to `.env.local`. Set the Supabase URL, publishable key,
   site URL, and a server-only Supabase Secret key. Configure the server-only
   credential encryption key with `openssl rand -base64 32`.
3. Configure `STUDIO_WORKER_API_URL` when a REST worker is available. Local
   sign-in, workspace creation, brief saving, and provider credential screens
   can run without it; research and production require the worker.
4. Allow `http://localhost:3000/auth/callback` in Supabase Auth redirect URLs,
   then run `npm install` and `npm run dev` here.
5. In Vercel, set this folder as the project root and add the production site
   URL to Supabase's Auth redirect allowlist.

## Secrets

Only the Supabase publishable key and project URL belong in browser-visible
variables. Keep `SUPABASE_SECRET_KEY`, `STUDIO_CREDENTIAL_ENCRYPTION_KEY`, and
`STUDIO_WORKER_API_URL` server-only. A Supabase Secret key bypasses RLS, so
server actions must continue to check the signed-in user and workspace role.
The Mac mini REST worker also needs a server key to authorize and run jobs. The
worker must receive the same credential-encryption key as Studio so it can
decrypt workspace provider credentials at job time.

## Product boundary

The Studio web app provides the hosted creator workflow. Its server actions
call `/v1/operations/{operation}` on the authenticated REST worker and save
workspace state through Supabase. The persistent worker runs local video
dependencies, durable jobs, and media delivery. The open-source MCP remains
self-hostable for external AI clients and keeps its own authentication and
deployment.
