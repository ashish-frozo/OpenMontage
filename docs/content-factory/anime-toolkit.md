# Anime toolkit

Integration of [makevoid/claude-make-an-anime](https://github.com/makevoid/claude-make-an-anime)
at `adc1a76eb4e77df47f42160c2c166350a76ad849` (MIT).
The upstream reference documents and licence are preserved in
`.agents/skills/anime-production/upstream/`. Runtime code is installed into
the ignored `.runtime/anime-toolkit` directory by
`python scripts/setup_anime_toolkit.py`. Ruby 3.2+, Bundler 4.0.20, Node,
FFmpeg, ImageMagick, Pillow/numpy and Chrome are needed for the relevant tasks;
macOS Swift is optional for Core Image finishing. Setup installs dependencies
but performs no paid generation. `ANIME_RUBY` and `ANIME_TOOLKIT_HOME` support
administrator-managed locations. Fal credentials use the existing configured
`FAL_KEY` or upstream `FAL_AI_API_KEY`; credentials are not accepted in inputs.

| MCP operation | Capability |
|---|---|
| `anime_project` | Initialize a story workspace, author plan/config/prompt files with hash checks, inspect status, read upstream production references |
| `anime_local` | Mix audio, p5 overlays/titles/subtitles, sprite tools, camera/continuity evidence, dialogue timeline, episode assembly, Swift VFX |
| `anime_generate` | Approved Fal character/location sheets, dialogue, score, keyframes and camera-directed shots |

Use existing animation/cinematic pipelines and their checkpoints. Project code
and prompts live under `projects/<id>/assets/anime/`; canonical artifacts still
live under `artifacts/`. Research and creative decisions belong to the calling
AI. There is no dependency on a Claude subscription or a second orchestrator.

Generation uses normal persistent factory jobs and idempotency. The wrapper
requires approved predecessors, actual user approval evidence, the current
plan hash and a positive estimate. Item-based steps accept one selected item.
An estimate reserves project budget; upstream does not enforce a provider
spending cap or report final billing. Paid results carry unknown actual cost,
retaining the budget reservation for reconciliation. Timeouts may leave remote
work running; inspect receipts before retrying. No live paid generation is
part of setup or automated tests.

Only named task allowlists are exposed. Local calls strip generation keys and
request-forcing environment variables. Arguments use workspace-relative paths;
escaping paths, absolute paths and Rake syntax injection are rejected. The
upstream Ruby configuration and p5 code remain trusted executable project
code, like authored renderer workspaces; this is not a sandbox for arbitrary
third-party projects. Local tasks may replace derived media, so retain approved
deliverables as separate versions.

Read the `anime-production` skill for scene planning, reference order, imports,
review requirements and handoff. Inspect doctor output for optional backends.
