---
name: rea-video
description: Local shot-by-shot reference analysis, VIDEO.md evidence packages, storyboards and caller-led visual review through Content Factory.
---
Read upstream/SKILL.md for the analysis taxonomy and evidence standards. Its
standalone commands are background knowledge; use the MCP operations below.
Preserve the active OpenMontage pipeline, approval gates and provider choices.
Discover openmontage:rea_video_analyze and openmontage:rea_video_review.
Inputs are existing project videos, at most 10 minutes. Download references
through existing source tools first. Output to a NEW assets/rea-<version> folder.
The adapter runs local measurements only: no VLM, OCR, ASR, stem separation or
paid generation. Optional packaging detection is offline. These disabled layers
must not be reported as completed. Use existing approved transcription tools if
speech evidence is needed. Do not treat the CLI's inferred production method,
AI/human source or suggested generation model as a verified fact or approved route.
Read VIDEO.md, then video/timeline.md and relevant shot pages; avoid dumping the
large breakdown.json into a cheap model's context. Use factory_inspect_frame
on storyboard/contact-sheet images. prepare_review creates tasks and an answer
template; actually inspect frames before writing answers with existing workspace
editing tools. apply_review merges those answers and refreshes reports.
Record uncertainty, timestamps and what is visibly observed versus inferred.
validate checks the VIDEO.md package. Report HTML is a local artifact, not a
public executable page. Existing media exports can share storyboard images.
For trend style labels, cite this reviewed shot evidence in factory_trend_label.
For remakes, feed findings into normal proposal/script/scene-plan stages; do not
invoke upstream paid remake-run or change the selected renderer automatically.
