# OpenShorts integration

Upstream: https://github.com/mutonby/openshorts, MIT license.
Reviewed revision: `0d455f419a10c184e06a4b9fd1932e0badb8a786`.
The pinned tool schemas retain upstream licensing in tools/openshorts/LICENSE.upstream.

Content Factory discovers six `openmontage:openshorts_*` operations:
process_video, get_job_status, list_clips, get_quota, add_subtitles, recut_clip.
They are permitted in clip-factory and podcast-repurpose assets stages.
They bridge the self-hosted upstream MCP endpoint through the normal validated
routes, approvals, job persistence and budget accounting. No upstream publication
operation is exposed. Read `.agents/skills/openshorts/SKILL.md` before production.

Set `OPENSHORTS_API_URL=http://127.0.0.1:8017` on the MCP host.
Remote URLs require HTTPS; an optional `OPENSHORTS_API_KEY` stays host-side.
The API returns a job id quickly: retain it, poll status, then list clip URLs.
A completed Content Factory submission job is not an upstream completed render.
Timeouts never trigger a second submission. Inspect upstream state first.
Mutation tools require an explicit conservative estimated_cost_usd; actual cost
is unknown and remains reserved under Content Factory's existing accounting.

Use a separate Python environment and checkout for the upstream service; its
ML packages must not replace the MCP's own dependencies. Run
`scripts/run_openshorts_backend.py` with that environment. It binds only loopback,
limits concurrency to one and caps upload/output retention at 3 GB each.
The host still needs headroom for model downloads and transient renders.

For an OpenAI-compatible model set `LLM_BASE_URL`, `LLM_MODEL`, and optionally
`OPENSHORTS_LLM_KEY_FILE` (path to a private key file). The launcher reads that
file at runtime. CPU Whisper and face tracking run locally; moment selection
uses this configured model. MCP does not supply inference by itself. An agent
can direct recuts by supplying source segment timestamps instead.

This connector returns upstream clip links. Download chosen clips into project
assets, inspect them, and register provenance before using local composition or
Content Factory media exports. An upstream link is not a local exported asset.

Mac mini installation: native isolated `.venv-openshorts` environment with
`ai.frozo.openshorts` user LaunchAgent. Apply `requirements-openshorts-compat.txt`
after upstream requirements. MediaPipe imports successfully on Apple Silicon;
its published wheel has a platform-metadata warning from `pip check`.
Readiness and a live quota request are verified; the first upstream clip render completed. The test found missing subtitle
support in the standard Homebrew FFmpeg build; use ffmpeg-full for captions.

The launcher checks FFmpeg subtitle support before starting and prefers the
Homebrew ffmpeg-full binary. Set OPENSHORTS_FFMPEG_DIR for another installation.
Upstream OpenAI-compatible token counts do not prove a zero-dollar cost; a
reported total_cost of 0 is treated as unknown for our job reservations.

Portrait canvas and portrait picture are different. `output_format: vertical`
sets the 9:16 canvas. For existing clips use `recut_clip` with
`vertical_layout: fill` to crop/track into a full portrait picture, `fit` to
preserve landscape with blurred padding, or `auto` to let the backend choose.
Fill loses content at the sides: inspect the subject and any screen text.
Do not combine vertical_layout with the legacy framing field.
