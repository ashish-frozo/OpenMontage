# OpenMontage Studio: hosted SaaS architecture

## Product promise

Turn a creator brief into a researched, on-brand video draft that a team can
review, revise, and export from one workspace. The agent remains the creative
director; Studio provides the secure workspace, approvals, production state,
and delivery surface.

Initial customer: an independent creator producing YouTube and Instagram
videos. The first product experience should help a creator move from a researched idea to an approved draft without asking them to install Python, Node, FFmpeg, or a local MCP process. The first experience should take a
new workspace from sign-in to a reviewable draft without asking the creator to
install Python, Node, FFmpeg, or a local MCP process.

## Product boundary

- OpenMontage remains an AGPL self-hostable engine and MCP server.
- Studio is the hosted control plane and creator-facing web application. Its
  workflows use server-side REST APIs and do not require an MCP connection.
- The open-source MCP is deployed independently for external AI clients. Studio
  and MCP can share production libraries without depending on each other's
  transport or uptime.
- Customers can connect their own generation-provider credentials in the
  initial paid pilot. Studio records estimated and actual usage separately;
  model charges go to the customer's provider account.
- A job is not approval. Research, script, scene plan, assets, and final render
  remain reviewable stage outputs.
- Publishing is a later capability. The first release creates and exports
  platform-ready files; it does not post without an explicit account grant and
  user approval.

## System shape

    Web Studio (Vercel) ── Supabase Auth + RLS
         │
         ├── Studio server actions and API routes
         ├── Postgres + private object storage
         └── authenticated REST worker API (Mac mini)
                    ├── operation registry and pipeline rules
                    ├── durable job dispatch
                    └── Remotion / HyperFrames / FFmpeg + providers

    External AI clients ── Open-source OpenMontage MCP (separate deployment)

### Control plane

Use Supabase Auth and Postgres for identities, workspaces, memberships,
projects, job records, usage ledger, and audit events. The confirmed hosted app
stack is Next.js App Router on Vercel with Supabase. Every customer-owned row
has a workspace_id; policies use membership checks. The browser never receives
the Supabase service-role key or provider credentials.

The Studio REST API validates a Supabase user session and current workspace
membership on every request. A caller-supplied project ID or workspace ID is
only a selector; it is never proof of access. The separate open-source MCP
keeps its own self-hosted authentication modes.

### Data and media plane

Use private object storage. Keys follow
workspace_id/project_id/artifact-path; clients receive short-lived signed links
only after an authorization check. Provider secrets live in a separate table as
envelope-encrypted ciphertext, with the encryption key held outside Postgres
(KMS/secret manager). Never log key material or return ciphertext to browser
clients.

### Job plane

The existing local service creates subprocesses and stores project data in
folders and SQLite. Keep that behavior for self-hosting. The hosted path uses
database-backed job records and a worker queue, with per-job leases, timeouts,
resource limits, progress, and isolated temporary storage. An uncertain paid
provider outcome is reconciled before any retry. Only the worker can update
job state or usage events.

### Trust and billing

Store immutable usage events for reservations, actual provider usage, and
releases/refunds. A plan limit is a guardrail, not a claim that provider billing
is capped. Start with subscription + workspace limits and BYOK; add platform
credits only after measuring real costs and support load. Stripe webhooks update
entitlements idempotently. Keep admin actions and membership changes in an
append-only audit log.

## First release scope

1. Sign in, create a workspace, invite a teammate, and set one brand profile.
2. Create a YouTube or Instagram brief and receive a validated production plan
   with research sources, format, tool availability, and estimated cost.
3. Approve a script and scene plan; watch durable job progress and review assets.
4. Revise individual scenes, render, and export a private, playable file.
5. See job history, actual usage, provider status, and workspace limits.

Leave multi-platform auto-publishing, trend dashboards, social account analytics,
and a built-in model marketplace outside the first paid pilot.

## Launch gates

- Tenant isolation: automated tests prove one workspace cannot read or mutate
  another workspace's projects, jobs, media, keys, or usage.
- Reliability: worker restart resumes or clearly reconciles queued/running work;
  paid jobs are never blindly retried.
- Cost: each operation has a preflight estimate, a hard workspace limit, and an
  auditable actual-cost record.
- Usability: a non-technical pilot user can connect, create, approve, and export
  without shell access or support intervention.
- Quality: measure first-pass approval, time to approved video, render failure
  rate, and the human editing still required.
- Trust: publish privacy, retention/deletion, terms, support, and incident
  response details before public signup.

## Implementation order

1. Supabase schema, RLS, workspace creation, and tenant-safe media paths.
2. Hosted auth and workspace-aware REST API authorization.
3. Durable queue and worker isolation, retaining the current self-hosted runner.
4. Creator-facing Studio UI and end-to-end draft/review/export flow.
5. Provider connection management, billing, usage limits, observability, and
   deployment automation.

## Current implementation status

The repository contains the Studio Supabase schema, RLS-scoped workspace and
project data, email-link sign-in, briefs, activity, brand profiles, and
encrypted provider credentials. Its durable queue, worker lease and
reconciliation logic, private media storage, workspace isolation, and local
production tools are implemented.

Studio is being moved from an MCP client to a first-party REST worker API. The
Studio UI and server actions now use a REST client, and `content_factory.studio_api`
provides user-session validation, workspace authorization, project checks,
operation dispatch, durable workers, and signed media delivery. The worker is
not yet installed on the Mac mini, `STUDIO_WORKER_API_URL` is not configured in
Vercel, and this code has not yet been deployed. The standalone OpenMontage MCP
remains a separate open-source interface; it is not a Studio dependency.

Before the Studio workflow is usable end-to-end, deploy the REST worker, add
the Supabase server key and worker URL as server-only configuration, confirm
the required migrations are applied, and verify research, job status, rendering,
and media export. Script and scene-plan review, richer research, worker process
isolation, billing, invites, and launch operations remain open.
