---
name: openshorts
description: Self-hosted long-video clipping, AI moment detection, reframing, captions and agent-directed recuts through OpenShorts.
---
Use the clip-factory or podcast-repurpose pipeline and preserve its approvals.
Discover `openmontage:openshorts_*` operations and read their schemas.
`process_video` downloads, transcribes, selects moments using the backend's configured model,
tracks faces and renders vertical clips. Confirm content rights before setting confirm_rights.
This consumes compute and possibly paid provider calls: supply a conservative estimated_cost_usd.
A returned job_id means queued, not finished. Persist it and poll get_job_status every 30–60 seconds.
Use list_clips for completed clip URLs. Add_subtitles styles captions; recut_clip accepts
agent-selected source segments and framing. This lets the calling AI direct the edit.
Upstream moment selection still uses its configured LLM; MCP transport does not supply inference.
Self-hosted OpenShorts supports an OpenAI-compatible backend through LLM_BASE_URL,
LLM_MODEL and optional LLM_API_KEY, including OpenRouter. No model/provider is switched silently.
On a timeout do not resubmit: first inspect the upstream job state and backend logs.
Download approved clips into the current project's assets directory before local composition,
review them, and register provenance. Upstream URLs are not Content Factory exported assets.
The connector does not expose upstream publishing; use the existing reviewed publishing workflow.

Portrait canvas and portrait picture are different. `output_format: vertical`
sets the 9:16 canvas. For existing clips use `recut_clip` with
`vertical_layout: fill` to crop/track into a full portrait picture, `fit` to
preserve landscape with blurred padding, or `auto` to let the backend choose.
Fill loses content at the sides: inspect the subject and any screen text.
Do not combine vertical_layout with the legacy framing field.
