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
- Studio is the hosted control plane and creator-facing web application.
- Customers can connect their own generation-provider credentials in the
  initial paid pilot. Studio records estimated and actual usage separately;
  model charges go to the customer's provider account.
- A job is not approval. Research, script, scene plan, assets, and final render
  remain reviewable stage outputs.
- Publishing is a later capability. The first release creates and exports
  platform-ready files; it does not post without an explicit account grant and
  user approval.

## System shape

    Web Studio ── Supabase Auth ── Control API / MCP
         │                             │
         ├── Postgres + RLS             ├── operation registry and pipeline rules
         ├── private object storage     ├── durable job dispatch
         └── signed media links         └── isolated rendering workers
                                              │
                                  Remotion / HyperFrames / FFmpeg
                                  configured generation providers

### Control plane

Use Supabase Auth and Postgres for identities, workspaces, memberships,
projects, job records, usage ledger, and audit events. The confirmed hosted app
stack is Next.js App Router on Vercel with Supabase. Every customer-owned row
has a workspace_id; policies use membership checks. The browser never receives
the Supabase service-role key or provider credentials.

MCP authentication must resolve a verified user subject to workspace
membership on every request. A caller-supplied project ID or workspace ID is
only a selector; it is never proof of access. Keep the existing owner-allowlist
mode for self-hosted installations, and add a separate workspace-aware hosted
mode.

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
2. Hosted auth and workspace-aware MCP/API authorization.
3. Durable queue and worker isolation, retaining the current self-hosted runner.
4. Creator-facing Studio UI and end-to-end draft/review/export flow.
5. Provider connection management, billing, usage limits, observability, and
   deployment automation.

## Current implementation status

The repository now contains a local SaaS foundation: the Supabase migration
defines workspaces, RLS-protected projects, engine/capability metadata,
service-role-only job leases, progress reports and reconciliation, private media
policies, provider-secret storage, usage events, and entitlements. The Next.js
Studio implements email-link sign-in, workspace creation, brief storage, a
capability-driven view, an RLS-scoped activity panel that polls only while
visible, and an owner/admin-managed brand profile whose values are snapshotted
into each new brief. Owners can also connect Studio to its configured MCP
endpoint: Studio creates a workspace-scoped token, stores it encrypted for
server use, verifies a Streamable HTTP handshake, and snapshots the returned
tool catalog. An authorized creator can now start a free five-result Wikipedia
search from an evergreen brief after a live MCP availability check and a
no-cost preflight. Studio saves an immutable research route, submits it only
after the creator clicks, and records that click as approval evidence; jobs
remain visible through the workspace activity mirror. Workspace members can
open a completed result and review up to five bounded HTTPS source leads. These
snippets are discovery leads rather than verified claims. Live-news research,
source retrieval and claim verification, script and scene-plan approval, and
social publishing are still unfinished. From any project row, Studio can
request a five-minute signed video preview/download link for an existing render
from the configured MCP host. Hosted renders now replicate to a private Supabase
Storage bucket and can be exported as signed links or bounded byte chunks after
the worker volume is replaced. Canonical MCP checkpoints mirror their latest
stage, status, and pending human approval into the matching Studio project. The new
`content_factory.hosted` mode verifies those tokens, checks each project ID
against the token workspace, and routes the existing `Factory` into a private
workspace directory; its current single-host deployment notes are in
`hosted-mcp.md`. Read-only MCP tokens are restricted using the registered tool
annotations. Hosted media export now supports signed, five-minute links served
from the private host volume, bound to a workspace and project and rechecked
against Supabase on download. Hosted submissions now enter Supabase's `jobs`
table through a producer-checked RPC that applies idempotency, entitlement,
concurrency and estimate-reservation guards. The MCP server's FastMCP lifespan
starts and stops a lease-claiming worker pool; `STUDIO_WORKER_CONCURRENCY`
controls its process-wide worker count (default 2). SQLite remains the
execution adapter and the self-hosted queue. Hosted results and usage
settlement are written to Supabase. Private media is indexed by workspace and
project in a service-role-only table; each MCP download ticket rechecks project
ownership and falls back to a five-minute object signed URL. A storage outage
marks replication pending while preserving the successful render result. If the
MCP host stops during work, that job enters reconciliation and is never
automatically retried. Fine-grained renderer progress remains open.
Workspace owners and admins can store provider credentials through an
AES-256-GCM server encryption boundary; a service-role-only database function
transactionally stores encrypted bytes, safe metadata, and an audit event.
Credential revocation erases the ciphertext and appends an audit event
transactionally; revoked labels can be reused for a replacement key.
The hosted MCP now resolves a submitted step to its registered tool, decrypts
the matching workspace credential in memory, and injects it only into that
job's worker environment. Selectors can receive credentials for their connected
candidate providers; tools can declare alternative or multi-value credential
shapes. Managed provider variables from the host are stripped from hosted
workers. The Studio and MCP host must share the encryption key; explicit key
rotation remains open.

This is not a live SaaS deployment yet. No OpenMontage Supabase project has
been selected or migrated, and the hosted MCP service is not deployed. Fine-
grained progress reporting, worker process/container isolation, provider key
rotation, invites, billing
integration, and launch operations still need implementation. Applying
the ordered migrations under `supabase/migrations/` to a live project is a
separate deployment action.
