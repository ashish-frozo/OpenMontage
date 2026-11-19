"""Optional MyShell MeloTTS local multilingual speech synthesis tool."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tools.base_tool import BaseTool, Determinism, ExecutionMode, ResourceProfile, RetryPolicy, ToolResult, ToolRuntime, ToolStability, ToolStatus, ToolTier


_LANGUAGES = {"EN": "English (speaker variants include US, UK, Indian and Australian)", "ES": "Spanish", "FR": "French", "ZH": "Chinese", "JP": "Japanese", "KR": "Korean"}


class MeloTTS(BaseTool):
    name = "melo_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "melotts"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL
    dependencies = ["python:melo", "python:soundfile"]
    install_instructions = "Install from upstream with: python -m pip install git+https://github.com/myshell-ai/MeloTTS.git. Model weights download on first use. Review model and voice terms before commercial distribution."
    agent_skills = ["content-factory-localization", "text-to-speech"]
    capabilities = ["text_to_speech", "multilingual", "offline_generation"]
    supports = {"multilingual": True, "offline": True, "voice_cloning": False, "locales": list(_LANGUAGES)}
    best_for = ["local CPU-capable speech synthesis", "English accents, Spanish, French, Chinese, Japanese and Korean"]
    not_good_for = ["Hindi or broad low-resource language coverage", "voice cloning"]
    input_schema = {
        "type": "object", "required": ["text", "language", "output_path"],
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "language": {"type": "string", "enum": list(_LANGUAGES), "description": "MeloTTS language/model key."},
            "speaker_id": {"type": "integer", "minimum": 0, "description": "Optional model speaker index; query factory_operation for full tool configuration."},
            "speed": {"type": "number", "default": 1.0, "minimum": 0.5, "maximum": 2.0},
            "device": {"type": "string", "enum": ["auto", "cpu", "cuda"], "default": "auto"},
            "output_path": {"type": "string", "description": "Destination audio file; WAV is recommended."},
        },
    }
    output_schema = {"type": "object", "properties": {"provider": {"type": "string"}, "language": {"type": "string"}, "speaker_id": {"type": "integer"}, "output": {"type": "string"}}}
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=3000, vram_mb=0, disk_mb=1200, network_required=True)
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = ["text", "language", "speaker_id", "speed", "device"]
    side_effects = ["may download model weights on first run", "writes audio file to output_path"]
    user_visible_verification = ["Listen for pronunciation and accent quality", "Confirm output duration fits the edit"]

    def get_status(self) -> ToolStatus:
        try:
            import melo  # noqa: F401
            import soundfile  # noqa: F401
            return ToolStatus.AVAILABLE
        except ImportError:
            return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if self.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(success=False, error="MeloTTS dependencies are missing. " + self.install_instructions)
        started = time.time()
        try:
            from melo.api import TTS

            language = inputs["language"]
            device = inputs.get("device", "auto")
            if device == "auto":
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            model = TTS(language=language, device=device)
            speakers = model.hps.data.spk2id
            speaker_id = inputs.get("speaker_id", next(iter(speakers.values())))
            if speaker_id not in speakers.values():
                return ToolResult(success=False, error=f"Unknown speaker_id {speaker_id} for MeloTTS {language}; available IDs: {sorted(speakers.values())}")
            output = Path(inputs["output_path"])
            output.parent.mkdir(parents=True, exist_ok=True)
            model.tts_to_file(inputs["text"], speaker_id, str(output), speed=inputs.get("speed", 1.0))
            if not output.is_file():
                return ToolResult(success=False, error="MeloTTS completed without producing the requested audio file.")
            return ToolResult(success=True, data={"provider": self.provider, "language": language, "speaker_id": speaker_id, "speaker_names": speakers, "output": str(output)}, artifacts=[str(output)], cost_usd=0.0, duration_seconds=round(time.time() - started, 2), model=f"MeloTTS/{language}")
        except Exception as exc:
            return ToolResult(success=False, error=f"MeloTTS synthesis failed: {exc}. Confirm this language model and its dependencies are installed.")
