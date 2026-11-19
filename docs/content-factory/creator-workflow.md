# Creator workflow improvements — 2026-11-15

## Available controls

- `factory_review_scene_plan`: validates schema/timing/ids, reports declared continuity mismatches, returns a fingerprint.
- `factory_preview_revision`: previews edits to the saved plan using fingerprint, timestamped notes, dot-field patches and persistent locks.
- `factory_save_revision`: saves a candidate without approval, preserves prior snapshots, invalidates saved routes and downstream checkpoints, refuses active jobs.
- `factory_revision_plan`: standalone preview for a caller-supplied immutable source plan.
- `openmontage:animatic`: renders storyboard images, footage or provisional text cards, temporary sound and sidecar captions. Reuses unchanged shots by content/parameter fingerprint. The assembled sequence and soundtrack rebuild.
- `openmontage:sound_design`: explicit sound cues, narration ducking, fades, silence, configurable loudness, measured output and optional separate role stems.
- `openmontage:media_transition`: picture transitions between real footage/images, with explicit overlap duration.
- `openmontage:creator_quality`: full-stream black/freeze/silence candidates, loudness measurement, shot/cut samples, caption timing and supplied text-box safe-area checks.
- `openmontage:editor_package`: portable OTIO, relative media links, source copies, separate audio tracks, captions, timeline notes and an unsupported-effects report.
- `openmontage:motion_scene`: added local image pan/zoom and reusable face sprites keyed to Rhubarb cues.

New scene plans use version 1.1, requiring shot_intent and narrative_role. Version
1.0 remains readable for existing projects. anime_scene, per-scene metadata and
continuity declarations are accepted. Version 1.1 checkpoints also reject duplicate
shot ids, invalid durations and overlapping/out-of-order scenes.

Existing gates remain binding. Review the animatic before final asset production.
A saved revision returns scene_plan to in_progress, revokes downstream approvals,
and retains old outputs as history. Reapprove the plan, reuse explicitly unaffected
assets, save fresh routes and replace the final review after composition.

The reviewer now permits intentional recurring subjects and brand motifs. It
preserves accessibility captions and asks for layout/timing changes to decorative
headlines when needed.

## Verification and limits

Tests exercise actual FFmpeg output, browser rendering, audio mixing, selective
animatic cache reuse, immutable revision snapshots, lock enforcement, continuity
warnings, OTIO reloading and MCP tool discovery. Benchmark JSON records contain
all model responses, attempts, provider-reported token usage and costs for ten
synthetic revision tasks. The model benchmark does not test tool selection,
complete production, voice quality, visual identity or artistic quality.

Quality reports require human adjudication: a freeze or silence can be intentional.
Safe-area checks use supplied boxes, not OCR; sampled frames do not prove character
identity or subtitle correctness. Sound stems are normalized isolated roles and do
not sum exactly to the ducked master. OTIO interoperability depends on the editor's
adapter; effects are reported, not silently claimed to round-trip. Motion sprites
must be supplied by the creator; arbitrary rig authoring and automatic viseme
placement are not implied.

## Reproduce DeepSeek benchmark

Run from the repository root (requires an existing OpenRouter credential in
OPENROUTER_API_KEY or ~/.config/openrouter/api-key):

```
.venv/bin/python scripts/benchmark_creator.py \
  --model deepseek/deepseek-v4.1-flash-1017 \
  --output /tmp/creator-benchmark.json
```

The run caps each task at two attempts, requests JSON with reasoning disabled,
and never retries uncertain transport failures. It edits only synthetic data.
`--self-test` checks the ten expected answers without making model calls.

## Voiceover shortlist

Kokoro is already represented by a local adapter and is a sensible lightweight
narration baseline. Chatterbox is a candidate for expressive/cloned multilingual
voices. VoiceStudio is a broader desktop voice/dubbing workflow; evaluate it as a
separate optional integration rather than assuming it is a TTS model or already
installed. A listening test on the Mac mini is still needed before selecting final
voices. Sources: https://huggingface.co/hexgrad/Kokoro-82M,
https://github.com/resemble-ai/chatterbox, https://github.com/debpalash/VoiceStudio.

## Completed verification

- Local suite: **119 passed**, including creator integration, Content Factory,
  checkpoint prerequisites/identity/validation and pipeline contracts.
- Mac mini suite: **49 passed** across its Content Factory and creator tests.
- Connected endpoint reports all five new native operations available after restart.
- Final DeepSeek run: **10/10 tasks, 10 attempts**, with reasoning disabled.
  Provider reported 9,956 tokens and $0.00031226976 for this run. Earlier results
  are retained: 8/10 with source-plan echoing; 9/10 with structured edits but the
  final response empty. The final harness handles empty content and explicitly
  disables optional reasoning for these bounded edit tasks.
- Host backup: `.runtime/backups/creator-20261115/pre-fix.tgz`.
