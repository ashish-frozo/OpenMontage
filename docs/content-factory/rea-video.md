# rea-video analysis adapter

Source: https://github.com/JuneYaooo/rea-video
Pinned reviewed revision: a274f48ac8911c415c46c21f7b78026e1638f0ef.
Upstream is Apache-2.0; copied skill/reference material retains LICENSE and NOTICE
in .agents/skills/rea-video/upstream/ . The upstream code runs as an isolated CLI.

Install a checkout at ~/WORK/rea-video and its base package in
.venv-rea-video using that environment's pip. Set REA_VIDEO_PYTHON to override
the default interpreter. The adapter requires FFmpeg/FFprobe on the host PATH.
MCP health checks CLI availability; it does not claim optional models are installed.

Two discoverable native operations:
- rea_video_analyze: project_id, video_path, analysis_dir, language, packaging.
  Sources must live in project assets/ or renders/ and last at most ten minutes.
  Outputs use a new assets/ directory; previous analyses are never overwritten.
- rea_video_review: summary, prepare_review, apply_review or validate. Applying
  review requires an explicit project JSON answers_path and records the reviewer.

The first integration supports offline analysis and caller-led visual review:
shot segmentation, contact sheets, measured visual/audio cues, layered VIDEO.md,
HTML reports and remake-plan evidence. VLM calls, whole-video model analysis,
OCR, speech recognition, stem models and paid remake generation are explicitly
disabled. Packaging detection can be enabled, with its uncertainty retained.
Use existing approved speech tools alongside this adapter when needed.

These operations run as durable Content Factory jobs with ordinary route and
stage validation. They are permitted in production research, idea, scene_plan
and assets stages. Read .agents/skills/rea-video/SKILL.md before analysis.
Reports are evidence to review, not reliable AI detectors or automatic creative
approval. Never turn a heuristic guess into a confirmed production-method claim.
The calling AI can inspect storyboard images and supply visual review answers.

VIDEO.md and bounded summaries are returned to avoid loading the large upstream
breakdown JSON into model context. Full reports stay inside the project. HTML is
not exposed through the public media export endpoint. Storyboard JPEGs can use
existing media exports. No new model credentials are needed for this mode.
