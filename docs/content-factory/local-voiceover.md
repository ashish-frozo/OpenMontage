# Local Kokoro and Chatterbox voiceover

Both providers are registered as native MCP operations and participate in
`tts_selector` discovery. No speech API key or per-request provider fee is needed.
Choose explicitly with `preferred_tool`; no silent model substitution is intended.

## Kokoro

```
{"preferred_tool":"kokoro_tts","text":"Your story starts here.",
 "language_code":"en-US","voice":"af_heart","speed":1.0,
 "output_path":"/absolute/project/assets/audio/narration.wav"}
```

The selector maps locale aliases to native Kokoro keys and supplies a matching
voice if omitted. Native `kokoro_tts` calls use a/b/e/f/h/i/j/p/z language keys.
`factory_local_voices(engine="kokoro")` lists installed voice files. Japanese and
Mandarin additionally require their Misaki extras; not every installed voice has
been listening-tested. Kokoro supports preset speakers, not reference cloning.

## Chatterbox

```
{"preferred_tool":"chatterbox_tts","text":"Your story starts here.",
 "variant":"english","language_code":"en","exaggeration":0.5,
 "cfg_weight":0.5,"temperature":0.8,"seed":1,
 "output_path":"/absolute/project/assets/audio/narration.wav"}
```

Omit reference_audio_path for the built-in speaker. For a chosen reference voice,
provide a clean local 3–30 second recording. The worker retains upstream
watermarking. Use short sections and the same reference across scenes. The
multilingual variant is a separate optional model installation; inspect
`factory_local_voices(engine="chatterbox")` before using it.

Both tools write WAV, report duration/sample rate/model revision and use atomic
output replacement. SSML and word timestamps are unsupported. Chatterbox uses
expression controls rather than voice IDs or speed/pitch settings. Use alignment
and editing tools after generation for captions and timing.

## Installation and isolation

Each engine has its own virtual environment. The MCP host never imports torch or
loads a speech model during tool discovery. The worker uses CPU by default on
Apple Silicon; explicit MPS enables PyTorch fallback. Override interpreter paths
with KOKORO_PYTHON / CHATTERBOX_PYTHON, and model roots with KOKORO_MODEL_DIR /
CHATTERBOX_MODEL_DIR when deploying outside the default checkout layout.

```
python3.12 -m venv .venv-kokoro
.venv-kokoro/bin/pip install -r requirements-localization-kokoro.txt
.venv-kokoro/bin/python scripts/setup_local_tts.py kokoro

python3.12 -m venv .venv-chatterbox
.venv-chatterbox/bin/pip install -r requirements-chatterbox.txt
.venv-chatterbox/bin/python scripts/setup_local_tts.py chatterbox
```

Setup records the resolved model revision and verifies a real short synthesis
before writing ready.json. Normal generation sets Hugging Face/Transformers
offline mode. Health verifies the interpreter and installed file sizes against
that successful setup record; it is not a fresh inference on every query.

Optional Chatterbox multilingual setup adds `--variant multilingual`. Keep
virtualenvs and `.runtime/tts` out of git. Model/voice files retain upstream terms.
Sources: https://github.com/hexgrad/kokoro and
https://github.com/resemble-ai/chatterbox.

## Mac mini verification

Kokoro generated a 5.125-second setup sample and a 2.8-second offline adapter
sample at 24 kHz. Chatterbox English generated a 4.56-second setup sample at
24 kHz with its Perth watermarking enabled. Perth requires setuptools 80.9.0
because its current package still imports pkg_resources. Peak protection scales
only when necessary to avoid clipping when writing 16-bit WAV.

Installed model revisions:
- Kokoro: f3ff3571791e39611d31c381e3a41a3af07b4987
- Chatterbox English: 5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18

The optional Chatterbox multilingual model has not been installed or verified.

Chatterbox also passed offline reference-voice synthesis using the synthetic
Kokoro sample: 2.96 seconds, 24 kHz, finite/non-silent output, peak 0.508. The Mac
mini passed 23 voiceover and Content Factory tests. Both restarted services expose
the new operations; live health reports available with network_required=false.
