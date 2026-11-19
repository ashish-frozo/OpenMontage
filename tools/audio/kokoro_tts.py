"""Optional Kokoro-82M local multilingual speech synthesis tool."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tools.base_tool import BaseTool, Determinism, ExecutionMode, ResourceProfile, RetryPolicy, ToolResult, ToolRuntime, ToolStability, ToolStatus, ToolTier


class KokoroTTS(BaseTool):
    name = "kokoro_tts"
    version = "0.2.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "kokoro"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL
    dependencies = []
    install_instructions = "Create .venv-kokoro, install requirements-localization-kokoro.txt, then run .venv-kokoro/bin/python scripts/setup_local_tts.py kokoro."
    agent_skills = ["local-voiceover"]
    capabilities = ["text_to_speech", "multilingual", "offline_generation"]
    supports = {"multilingual": True, "offline": True, "voice_cloning": False, "locales": ["en-US", "en-GB", "es", "fr", "hi", "it", "ja", "pt-BR", "zh"]}
    best_for = ["local, no-per-request-cost narration", "English, Spanish, French, Hindi, Italian, Japanese, Portuguese and Chinese voice variants"]
    not_good_for = ["voice cloning", "languages or accents outside the installed model's voice set"]
    input_schema = {
        "type": "object", "additionalProperties": False, "required": ["text", "language_code", "voice", "output_path"],
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": 5000},
            "language_code": {"type": "string", "enum": ["a", "b", "e", "f", "h", "i", "j", "p", "z"], "description": "Kokoro language key: a=US English, b=British English, e=Spanish, f=French, h=Hindi, i=Italian, j=Japanese, p=Brazilian Portuguese, z=Chinese."},
            "voice": {"type": "string", "pattern": "^[abefhijpz][fm]_[a-z0-9_]+$", "description": "Voice identifier supported by the chosen language, e.g. af_heart, bf_emma, ef_dora, ff_siwis, hf_alpha, if_sara, jf_alpha, pf_dora, zf_xiaobei."},
            "speed": {"type": "number", "default": 1.0, "minimum": 0.5, "maximum": 2.0},
            "device": {"type": "string", "enum": ["auto", "cpu", "mps", "cuda"], "default": "auto"},
            "output_path": {"type": "string", "description": "Destination WAV path."},
        },
    }
    output_schema = {"type": "object", "properties": {"provider": {"type": "string"}, "language_code": {"type": "string"}, "voice": {"type": "string"}, "output": {"type": "string"}}}
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=2500, vram_mb=0, disk_mb=500, network_required=False)
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = ["text", "language_code", "voice", "speed"]
    side_effects = ["writes audio file to output_path"]
    user_visible_verification = ["Listen for pronunciation and accent quality", "Confirm output duration fits the edit"]

    def get_status(self) -> ToolStatus:
        from lib.local_tts import health
        return ToolStatus(health('kokoro')['status'])

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        import jsonschema
        from lib.local_tts import synthesize, model_dir
        try:
            jsonschema.validate(inputs, self.input_schema)
        except jsonschema.ValidationError as exc:
            return ToolResult(success=False, error=exc.message)
        if not inputs['voice'].startswith(inputs['language_code']):
            return ToolResult(success=False, error='Voice prefix must match language_code')
        if not (model_dir('kokoro')/'voices'/(inputs['voice']+'.pt')).is_file():
            return ToolResult(success=False, error='Voice is not installed; use factory_local_voices to choose an installed voice')
        return synthesize('kokoro', inputs)
