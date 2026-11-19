# Content Factory MCP

An agent-directed MCP interface for OpenMontage with independently installed
library adapters. The calling AI chooses the pipeline and per-stage operations
using capabilities, instructions and user preferences. The server validates
and persists those choices and runs individual jobs. There is no second LLM,
keyword-based creative router, or Python production orchestrator.

## Start and connect

From the repository, with the existing core environment installed:

```sh
.venv/bin/python -m pip install -r requirements-mcp.txt
.venv/bin/python -m content_factory
```

The default transport is local stdio. No public HTTP endpoint is enabled.
For a client that may start in another working directory, use the launcher:

```json
{
  "mcpServers": {
    "content-factory": {
      "command": "/absolute/path/OpenMontage/.venv/bin/python",
      "args": ["/absolute/path/OpenMontage/scripts/content_factory_mcp.py"]
    }
  }
}
```

Equivalent Codex configuration:

```toml
[mcp_servers.content-factory]
command = "/absolute/path/OpenMontage/.venv/bin/python"
args = ["/absolute/path/OpenMontage/scripts/content_factory_mcp.py"]
```

`OPENMONTAGE_PROJECTS_DIR` or `--projects-dir` overrides the project root. Point
Backlot at the same root. API credentials remain in the existing environment;
they are not stored in route parameters. Install plugins into the same Python
environment as the MCP server and restart it after installation.

## Available interface

| Tools | Purpose |
|---|---|
| `factory_plugins`, `factory_operations`, `factory_operation` | Discover adapters, capability families, every native input schema and live availability |
| `factory_config_schema` | Discover project defaults, constraints and route schemas |
| `factory_customer_profiles`, `factory_customer_profile`, `factory_save_customer_profile`, `factory_customer_profile_history` | Create, inspect, update and audit versioned customer profiles |
| `factory_pipelines`, `factory_instruction`, `factory_artifact_schema` | Retrieve production manifests, skills and canonical artifact schemas |
| `factory_styles`, `factory_style` | Browse styles and retrieve a full OpenMontage playbook or community recipe with compatibility and provenance |
| `factory_motion_resources` | Discover motion skills and renderer template libraries with licensing and integration status |
| `factory_create_project`, `factory_project`, `factory_configure_project` | Create projects, inspect progress, replace configuration with revision checking |
| `factory_stage_context`, `factory_checkpoint` | Read stage directors and save schema-validated artifacts through existing approval gates |
| `factory_validate_route`, `factory_save_route` | Validate or persist AI-authored routes with reasons and alternatives |
| `factory_submit_job`, `factory_job_status`, `factory_cancel_job`, `factory_reconcile_job` | Durable subprocess execution, logs, cancellation and abandoned-job reconciliation |
| `factory_write_workspace_file`, `factory_read_project_file`, `factory_outputs` | Author scene source, inspect artifacts and retrieve output paths |
| `factory_projects`, `factory_routes`, `factory_jobs` | Discover saved work and resume after a client reconnect |

MCP resource `factory://guide` carries the production contract from
`skills/guide.md` (a symlink to the root `AGENT_GUIDE.md`; the server also falls
back to that root file if the alias is missing), and
`factory://skills/localization` gives the multilingual production workflow. The
same workflow is available through `factory_instruction(name="content-factory-localization")`.
The `create_content` prompt starts discovery and agent-directed planning.

The community motion/style library is documented in
[`motion-library.md`](motion-library.md). It is searchable through the style
and motion-resource MCP tools. Recipes guide renderer choice; they do not make
an uninstalled renderer available.

## Configuration

`factory_config_schema` exposes the complete versioned schema. Example project
configuration (native fields are adapter-specific):

```json
{
  "customer_profile_id": "frozo-brand",
  "routing": {
    "mode": "mixed",
    "preferred_plugins": ["lemo"],
    "pinned_operations": {"assets": "lemo:render"},
    "local_only": true,
    "allow_network": false,
    "priorities": ["visual quality", "brand consistency", "cost"]
  },
  "brief": {
    "platform": "YouTube Shorts",
    "duration_seconds": 45,
    "language": "en",
    "style": "watercolor",
    "brand": {"colors": ["#113355", "#FAF6EF"]}
  },
  "native_defaults": {
    "lemo:render": {"fps": 30, "width": 1080, "height": 1920, "workers": 2}
  },
  "locked_params": {"lemo:render": {"width": 1080, "height": 1920}},
  "timeout_seconds": 1800,
  "max_concurrent_jobs": 2,
  "max_job_estimate_usd": 0,
  "require_job_approval": true
}
```

- `auto`: the AI chooses among allowed candidates; all hard constraints still apply.
- `directed`: every planned stage needs an explicit `pinned_operations` choice.
- `mixed`: pins constrain selected stages; the AI chooses the remainder.
- Empty `allowed_plugins` allows all installed plugins. Exclusions are hard;
  preferences are soft. Stage pins currently select a single operation for that
  stage; leave a stage unpinned when it needs several kinds of assets.
- Native values merge shallowly: defaults, locked values, then step parameters.
  An explicit step value conflicting with a lock is rejected. Lock a provider's
  `model`, `voice`, `seed`, `codec`, `render_runtime`, etc. using its actual schema.
- `brief` and `priorities` are planning context for the AI, not magically applied
  render settings. The agent maps them into the native schemas.
- `max_job_estimate_usd` is an estimate threshold, **not a billing cap**. Estimates
  come from each adapter and may be inaccurate. Provider billing and OpenMontage's
  production budget protocol still apply. Project-wide conservative reservations are supported through `max_project_estimate_usd`, including external agent costs. See [automatic workflows](automatic-workflows.md).
- Local/network flags filter declared runtime requirements. They are not an OS
  sandbox: authored pages and trusted plugins can access local files/network.
- Config changes increment a revision and invalidate saved routes. Running jobs
  retain their already submitted snapshots. Pipeline identity is immutable.

### Customer profiles

Create a profile with `factory_save_customer_profile` using a stable `profile_id`
and the `customer_profile` schema from `factory_config_schema`. Omit
`expected_revision` for the first save; subsequent saves must provide the current
revision. Every save is retained in `factory_customer_profile_history`. Attach
the profile using `ProjectConfig.customer_profile_id`.

Profiles hold brand identity, audience, voice, visual direction, publishing
defaults, production preferences, safety guidance and custom notes. The agent
receives the selected profile from `factory_project` and
`factory_stage_context`; it should apply the profile to its proposal, route,
native parameters and review. The server merges profile operation defaults before
project defaults and route parameters, and enforces profile allowed/excluded
rules, network policy, local-only constraints, cost ceilings and approval
requirements. Validated routes pin the profile revision, so a profile edit
requires a new route. Safety notes guide the agent but do not prove factual
accuracy or rights.

Publishing defaults accept a default `language`, optional `source_language`,
multiple `target_languages` and `caption_languages`, a `localization_mode`, and
provider-specific `voice_preferences` keyed by locale. Empty target/caption
lists inherit the default language. These fields guide the AI route; the AI must
still map them into each selected operation's native parameters. For the actual
localization pipeline and optional provider installs, read
`factory://skills/localization` before planning.

`logo_asset_ids` and `reference_asset_ids` are references for the agent to use
when those assets are available in project files or another connected asset
store; this profile API does not upload binary files yet.

Profiles are persisted in `.content-factory/customer_profiles.sqlite3` under the
factory project root. The current remote deployment still has a single shared owner and project
root; this feature does not provide tenant isolation. A hosted multi-customer
service needs account-scoped profile and project authorization before onboarding
outside users.

## Production sequence

1. Ask the AI for a video. It reads `factory://guide`, discovers capabilities,
   inspects native parameter schemas and relevant plugin instructions, and
   selects a pipeline. It distinguishes user preferences from hard requirements.
2. Create the project with configuration and open the returned Backlot command.
3. Read stage context, produce canonical artifacts and checkpoint them. Required
   human gates still apply. `approval_evidence` records the actual user statement;
   it is an audit field provided by the trusted calling agent, not an independent
   authentication mechanism.
4. Author source through workspace-file tools if necessary. The Lemo adapter
   renders an existing deterministic page; it does not author that page itself.
5. Validate and save a route. Example step in the animation pipeline:

```json
{
  "request": "A watercolor short about solar power",
  "steps": [{
    "id": "scene-one",
    "stage": "assets",
    "operation": "lemo:render",
    "params": {
      "workspace": "/absolute/path/projects/solar/workspaces/scene-one",
      "output_path": "/absolute/path/projects/solar/assets/video/scene-one.mp4",
      "mode": "render"
    },
    "reason": "The user requested the Lemo watercolor treatment.",
    "depends_on": []
  }]
}
```

6. Submit a saved step after predecessor gates, with a stable idempotency key.
   Poll the job. Same key/work returns the existing job; different work with the
   same key is rejected. Jobs never automatically advance checkpoints.
7. Review results, update canonical artifacts and continue the pipeline. Each
   change of approved provider/runtime requires the normal decision-log entry.

Routes are immutable SQLite records containing resolved parameters, versions,
reasons and alternatives. Dependencies must name earlier steps and are checked
for completion. Artifact types describe interfaces; this version does not infer
converters or substitute upstream output paths automatically. Supply explicit
paths and conversion operations when formats differ.

## Built-in adapters

**OpenMontage:** exposes its existing registry, native schemas, health, cost
estimates and execution. Pipeline manifests still determine which operations
can run at each stage. Optional dependency failures are reported as plugin
discovery errors rather than silently advertising a working adapter.

**Lemo:** wraps the standard `lemo_render` BaseTool, registered in the animation
assets stage. Modes: `render`, `preview`, `readcheck`. Exposes dimensions, fps,
workers, timestamps, page query, WebGL backend and readability settings. The
result is a scene clip, not a replacement for final `video_compose` runtime.
Use the approved FFmpeg/Remotion/HyperFrames path to assemble the final film.

Lemo must be installed separately: pin a checkout of
https://github.com/lemomo-ai/lemo-opuscar, follow its core setup, and set
`LEMO_OPUSCAR_HOME`. The server does not clone, update, install models or invoke
setup scripts on discovery. Its native page contract and style instructions are
read from the installed checkout. The adapter can be tested while the runtime
is absent; actual Lemo rendering requires a working upstream browser/runtime.

## Job lifecycle and boundaries

Jobs persist in `projects/<id>/factory.sqlite3`; logs/results are under
`artifacts/factory-jobs/`. Detached supervisors survive an MCP client disconnect
and enforce per-job wall time. Per-project concurrency admission is transactional.
Direct submission rejects work beyond the concurrency limit. Use `factory_enqueue_job` and `factory_dispatch_queue` for durable deferred admission. No automatic retry of failed or uncertain paid work occurs.

Cancellation stops the local process group on POSIX; a remote provider may keep
running. After a supervisor crash, `factory_reconcile_job` marks the job
interrupted only if its recorded PID is gone. Inspect outputs/provider status
before creating another job. This implementation targets macOS/Linux and trusted
single-user local clients; Windows process-group cancellation and authenticated
remote multi-tenant hosting are not implemented.

### Remote MCP authentication

The remote service uses GitHub OAuth for ChatGPT and Claude. OAuth access
tokens are short-lived; OAuth clients must persist and rotate the refresh token.
The server cannot update a bearer token already stored inside an MCP client.

For a client that cannot reliably refresh OAuth, an operator may configure a
separate `harness_api_key` in `~/.config/content-factory/remote.json`. It is a
long-lived bearer credential, associated with the first configured GitHub user
ID, and remains valid until rotated or removed. Set or rotate it interactively
on the server with:

```sh
.venv/bin/python scripts/configure_factory_harness_key.py
```

Use a randomly generated value of at least 32 characters. The configuration is
written with mode `0600`; restart the service after changing it. Store the same
key in the client's secret environment settings and pass it as
`Authorization: Bearer <key>`. For `mcp-remote`, use its `--header` option with
an environment variable, for example `Authorization: Bearer ${CONTENT_FACTORY_MCP_TOKEN}`.
Providing an Authorization header selects static bearer auth in `mcp-remote`,
so it will not run its OAuth flow for that connection. Rotate by changing both
the server configuration and the client secret together. ChatGPT and Claude can
continue to use GitHub OAuth independently.

Treat this key like a password: keep it out of command arguments, logs, source
control, and chat. Anyone holding it can use the MCP server as the configured
owner until the key is rotated.

## Add another library

See [plugin-authoring.md](plugin-authoring.md). No changes to the MCP server or
AI routing code are required. A new production capability may need a declarative
pipeline permission or a new pipeline manifest/director skill.

## Verification

```sh
.venv/bin/python -m pip install -r requirements-dev.txt -r requirements-mcp.txt
.venv/bin/python -m pytest tests/content_factory -q
```

Tests cover schema discovery, real MCP stdio transport, plugin isolation,
configuration locking/revisions, route constraints, pipeline gates, path bounds,
and a real FFmpeg render through the detached worker. Lemo's command mapping is
tested without installing its models or rendering a full Lemo film.

For short, intentionally silent Remotion clips, set `edit_decisions.metadata.tailPaddingSeconds` to `0`, `edit_decisions.metadata.target_duration_seconds` to the desired length, and `edit_decisions.metadata.audio_intent` to `silent`. The compose adapter forwards tail padding to Remotion and the final review accepts explicit silence. A sole 1080x1920 asset now selects the TikTok output profile automatically when `profile` is omitted; pass an explicit profile to override it.

Rendered paths belong to the server host. `factory_export_media` returns expiring playable links on remote MCP or bounded base64 chunks on any transport. `factory_outputs` includes download links; media URLs support range requests.

## Creator workflow
See [creator-workflow.md](creator-workflow.md) for animatics, continuity, precise
revisions with locks, sound cues, temporal review, editor handoff and the DeepSeek
revision benchmark. Use factory_preview_revision with a saved project to avoid
asking a small model to rewrite the original plan.

Local speech providers: see [local-voiceover.md](local-voiceover.md) for Kokoro,
Chatterbox, installed voice discovery and isolated offline runtimes.

Automatic research-to-delivery workflows: see [automatic-workflows.md](automatic-workflows.md).

Playable downloads and chunked exports: [media-export.md](media-export.md).
