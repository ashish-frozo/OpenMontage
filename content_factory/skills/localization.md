# Content Factory localization skill

Use this skill for translation, multilingual captions, voiceover, dubbing, and
per-language video variants. The MCP is an agent-directed workflow engine: select
and explain the route, use the existing pipeline checkpoints, and do not silently
substitute a provider or skip human review.

## 1. Capture locale intent

- Read the customer profile. `publishing.language` remains the backwards-compatible
  default locale. Prefer `publishing.target_languages` when present; otherwise use
  that single `language` value.
- `source_language: "auto"` requests source-language detection, not a guarantee
  that every downstream translator supports it. Resolve the source locale before
  calling a translator that requires an explicit language.
- Respect `caption_languages`, `localization_mode` (`subtitles`, `voiceover`,
  `dubbing`, or `multi_variant`), `voice_preferences`, brand voice, protected
  names, glossary, and pronunciation instructions from profile or brief.
- Ask only when source, target, or deliverable mode materially changes the result
  and cannot be inferred from the brief/profile.

## 2. Discover a compatible route

Call `factory_operations` filtered by capability (`analysis`, `translation`,
`subtitle`, `tts`, or `avatar`) and inspect exact operation schemas and health.
Use `factory_operation` for full options. A provider can be registered while its
optional package or locale model is missing.

Current native localization choices include:

- `openmontage:transcriber` — local faster-whisper transcription and language
  detection, with word timestamps.
- `openmontage:argos_translate` — optional offline text or SRT translation.
  Source/target packages must be installed. The engine does not enforce a custom
  glossary; preserve terms explicitly and request human review.
- `openmontage:kokoro_tts` — optional local Kokoro-82M synthesis. Choose a language
  key and a voice that match it in the operation schema.
- `openmontage:melo_tts` — optional local MeloTTS for its listed English variants,
  Spanish, French, Chinese, Japanese, and Korean models.
- Existing provider TTS tools (including Piper, Google, and others) may fit better.
  Compare exact locale/voice support, health, latency, resource needs, and user
  routing constraints. Do not assume Piper's default voice is multilingual.

These tools are optional integrations, not mandatory dependencies. If one is
unavailable, show available alternatives and ask before a material provider/model
change. Project `local_only` and `allow_network` constraints apply.

## 3. Use a staged workflow

For source video, use the `localization-dub` pipeline. Transcribe first, retaining
timecodes and speaker information where available. Translate the script or SRT
for each requested target locale. Review meaning, idioms, claims, brand terms,
names, legal copy, reading speed, and line breaks before synthesis. Use the
subtitle tool for caption assets. For voiceover/dubbing, synthesize each locale,
align it to source pacing, then mix or replace audio only according to the
approved mode. Lip-sync is a separate optional stage; translated audio alone
does not create lip-sync.

For newly authored content, create an approved localized script and render a
variant per locale where on-screen text, captions, narration, or imagery changes.
Record locale-specific assets and decisions in canonical artifacts. Keep shared
visual timing consistent where possible.

## 4. Cost, licensing and review

Local inference has no per-call provider fee, but consumes Mac mini CPU/RAM/disk;
first use may download model weights. Check model and voice-data terms separately
from library code before redistribution or commercial use. Argos translation
packages and individual Piper voices can have their own terms. Never infer model
license from the Python library license.

Translation and synthesis are drafts. Preserve the source transcript, make
translated text reviewable before voice generation, and require a fluent human
reviewer for high-stakes or brand-sensitive content. Verify pronunciation,
caption rendering, timing drift, audio levels, and each final locale variant.

## Optional installation

Install only the provider(s) you intend to use. Install Argos and Kokoro from
their provider-specific requirement files. Install MeloTTS separately using its
upstream source instructions:

```sh
python -m pip install git+https://github.com/myshell-ai/MeloTTS.git
```

```sh
python -m pip install -r requirements-localization-argos.txt
python -m pip install -r requirements-localization-kokoro.txt
```

Then install the needed Argos language-pair packages and check operation health.
The MCP does not automatically download or install packages.
