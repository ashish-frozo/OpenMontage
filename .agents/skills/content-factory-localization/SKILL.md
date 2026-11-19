---
name: content-factory-localization
description: Route multilingual Content Factory requests across transcription, translation, subtitles, voiceover, dubbing, and per-language video variants.
---

# Content Factory localization

When using the Content Factory MCP, load `factory://skills/localization` (or call
`factory_instruction` with `name="content-factory-localization"`) for the full
workflow and profile contract. Discover live operation schemas and health with
`factory_operations`; do not rely on this short index for current availability.

OpenMontage already exposes local faster-whisper transcription and has existing
provider TTS tools. Optional native localization adapters are:

- `openmontage:argos_translate` for local text and SRT translation; language-pair
  model packages must already be installed.
- `openmontage:kokoro_tts` for local Kokoro-82M synthesis with language-matched
  voice prefixes.
- `openmontage:melo_tts` for local MeloTTS languages and speaker IDs.

Use `publishing.target_languages` when set, otherwise the profile's backwards-
compatible `publishing.language`. Keep source transcript, translated text,
per-locale captions/audio, and final renders reviewable as separate artifacts.
Run the existing `localization-dub` pipeline for source-footage localization.
Translation, speech, captions, and lip-sync have separate coverage; verify each
capability for every requested locale and require human language review.

These are optional tools. Do not install packages or download model weights
without user direction. Inspect operation health first; obey local/network
preferences and ask before a material provider substitution.
