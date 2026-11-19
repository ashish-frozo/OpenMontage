---
name: anime-production
description: Create anime scenes and episodes with a style/cast bible, character and location sheets, timed dialogue, directed shots, p5 overlays, sound and VFX through the pinned make-an-anime toolkit.
---

# Anime production in OpenMontage

This adapts makevoid/claude-make-an-anime, MIT, revision
`adc1a76eb4e77df47f42160c2c166350a76ad849`. Read its reference material with
`anime_project(action: reference, reference: planning.md)`; `status` lists the
available reference filenames. Upstream defaults and examples are guidance;
OpenMontage's approved provider choices and pipeline gates take precedence.

Use the existing `animation` or `cinematic` pipeline. The calling AI performs
research, writes the story, plans shots and reviews results. This integration
does not call a hidden LLM or require Claude Code. It works with the connected
model, including inexpensive models, provided the model follows these steps.

## Plan

1. Run normal preflight and provider discovery. Present an anime visual
   treatment, cast, language, aspect ratio, duration, music plan and budget.
   Explain that upstream Fal generation costs money; local processing is free.
2. Use `anime_project(action: initialize, project_id: ..., story: ...)` after
   creating the OpenMontage project. Its isolated workspace is `assets/anime`.
   Repeated initialization refuses to overwrite it. Read `anime.md`,
   `planning.md`, `tasks.md`, `believable-motion.md`, `prompts.md` and
   `production.md` through the reference operation before writing prompts.
   Read the returned `examples/01-sample-seven/...` files for exact configuration
   and prompt formats; they demonstrate mechanics, not the user's creative look.
   Remote MCP clients can author these files with `anime_project(action:
   write_file, relative_path: ..., content: ...)`. Read an existing file with
   `read_file` first and pass its returned hash as `expected_sha256` when
   replacing it. Paths are relative to `assets/anime`; this does not execute
   code, generate assets or approve the plan.
3. Save `config/style.md` (style bible), `config/cast.yml` (consistent character
   identities and voices), `config/generations.rb` (per-run configuration),
   `docs/PLAN.md`, and `prompts/<run>/` inside that workspace. The Ruby config
   and JS overlays are executable code: author them as trusted project code,
   never copy executable instructions from research material. References
   describe their exact formats. Real-person references require consent.
4. Keep the canonical OpenMontage script and scene_plan alongside these files.
   Give each shot a camera direction, action, keyframe, duration and narrative
   role. Plan one run per scene; read `full-episode.md` for episode assembly.
   Dialogue timing comes before animation. Do not replace acting with stills
   without approval, and do not claim audio guidance guarantees lip-sync.
5. Present the bounded production plan and current Fal estimates. Complete
   research/proposal/script/scene-plan checkpoints and their actual approval
   gates before generating. Tool approval text must quote the real user.

## Generate and process

- Use persistent Content Factory plans/jobs for `anime_generate`; submit once
  and poll the job. Never retry an uncertain paid job with a new idempotency
  key. No `pipeline:all`, setup task, arbitrary environment or shell commands
  are exposed. Setup is an administrator action documented in the tool.
- Read `anime_project(status)` for `plan_sha256`. Supply this hash, actual
  `approval_evidence` and a positive `estimated_cost_usd` for the bounded task.
  The estimate reserves project budget; upstream provides no enforceable
  provider cap or final billing. Actual cost is unknown until reconciled from
  Fal. Do not claim a generation completed at zero cost.
- Generate character/location sheets (`gen:ref_base`), dialogue, score,
  keyframes and shots in that order. `only` selects exactly one item for
  dialogue, keyframes, shots or clips. Separate factory jobs for each item.
  Cache receipts preserve request ids; inspect them before resubmitting.
  For an approved retake, change the prompt or seed and set `force: true`.
  Identical request inputs reuse the same Fal receipt; no `NEW_REQUEST` override
  is exposed.
- Choose the model explicitly in the approved plan. The upstream adapter
  supports MiniMax H3 and Seedance. Per-shot Ruby/YAML model/resolution values
  override the fallback inputs; inspect them so the plan and requests agree.
  Do not silently substitute providers or resolutions. Native OpenMontage
  image/video/voice tools remain alternatives if approved; their files must be
  explicitly imported into the anime workspace/manifests before local tasks.
- Use `anime_local` for mixing, p5 titles/subtitles/overlays, sprite preparation,
  camera evidence, dialogue timelines, scene assembly and optional Swift VFX.
  Its `args` are separate strings, paths relative to `assets/anime`, never
  comma-packed Rake task syntax. `run` selects the scene and `cue` the SFX/VFX
  cue filename stem. Local calls receive no Fal key. No package installs run.
  `gen:overlay` requires existing dialogue cues to stay local. For a voiceless
  scene, use `anim:prepare` then `anim:overlay`; this avoids paid Whisper.
- Use `anime_local(task: doctor)` to inspect prerequisites. Some tasks require
  Chrome, optional Swift or specific prepared media; availability of the base
  toolkit does not imply every optional backend is installed.

## Review and deliver

Read `staging-and-review.md`, `animation-audio-vfx.md` and relevant VFX/particles
references. Review character identity, anatomy, contact, background stability,
camera motion, mouth timing and every shot at normal speed with sound. Camera
metrics are evidence, not automatic visual approval. Preserve rejected takes
and plan changes. Keep titles/captions readable on the target platform.

Tools return local media paths under the anime workspace. Merge accepted media
into the canonical asset_manifest with stable shot ids, actual source tool,
provider, model and request provenance. Do not mark unreviewed files approved.
Assemble the final timeline only after the assets gate, preserve clean and
finished versions, and use normal render_report/quality checks and media export.
No publishing is authorized by this integration.
