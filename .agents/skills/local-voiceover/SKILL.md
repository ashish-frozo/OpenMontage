---
name: local-voiceover
description: Local Kokoro and Chatterbox narration, installed voice discovery and expressive controls.
---
Read factory_local_voices before selecting a voice. Use tts_selector with
preferred_tool=kokoro_tts or chatterbox_tts to preserve explicit routing, then use
normal assets-stage routes and approval gates. Generate a short sample before
long narration. Both write WAV; align captions separately (no word timestamps).

Kokoro: language_code a/b/e/f/h/i/j/p/z maps to US/UK English, Spanish, French,
Hindi, Italian, Japanese, Brazilian Portuguese and Mandarin. Select a matching
installed voice id. The selector accepts common locale aliases and supplies a
language-matched default voice. Speed 0.5–2.0. Japanese/Chinese need optional G2P
packages. It cannot clone a voice. Keep paragraphs below 5,000 characters.

Chatterbox: default variant english, optional multilingual must be installed.
Use language_code en for English. For multilingual, use upstream language ids.
Omit reference_audio_path for the default speaker or supply a clean 3–30 second
reference of a voice the user is authorized to use. Start exaggeration=0.5,
cfg_weight=0.5, temperature=0.8, seed=1. Use short sections (max 1,000 characters)
and the same reference across scenes. Preserve upstream watermarking. It does
not accept a Kokoro voice id, SSML, or voice-speed controls.

Runtimes are isolated in .venv-kokoro and .venv-chatterbox. Setup downloads weights
and verifies actual speech; normal synthesis sets offline mode and uses local
model files. CPU is the conservative default on Apple Silicon; explicit MPS is
available with fallback enabled. Listen for pronunciation, skipped/repeated words,
identity consistency and timing. Health is based on installed files and a successful
setup smoke test, not a fresh synthesis or a guarantee of every language/voice.
