# OpenShorts clip generation and review
Read `.agents/skills/openshorts/SKILL.md` and discover operation schemas/health.
Submit process_video through a validated Content Factory route and stable key.
Record the returned upstream job_id and poll every 30–60 seconds. Never replay
uncertain writes. A completed submission job is not a completed clip render.
On completion list clips; copy selected files into the project's assets folder.
Validate codecs, dimensions, duration, audio and caption timing; inspect frames.
Record source segments and provider/model provenance in asset_manifest.
Checkpoint awaiting_human and present clips for review. Do not claim approval
or publish them. If the backend fails, report its actual stage and error.
