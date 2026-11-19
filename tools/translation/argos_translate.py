"""Offline Argos Translate adapter for prose and timed SRT subtitles."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from tools.base_tool import BaseTool, Determinism, ExecutionMode, ResourceProfile, RetryPolicy, ToolResult, ToolRuntime, ToolStability, ToolStatus, ToolTier


_SRT_BLOCK = re.compile(r"(?P<header>\s*\d+\s*\n\s*\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}(?:[^\n]*)\n)(?P<body>.*?)(?P<tail>\s*)\Z", re.S)


def _language_code(value: str) -> str:
    """Argos packages use language codes; accept BCP-47 and use its base tag."""
    return value.strip().replace("_", "-").split("-", 1)[0].lower()


class ArgosTranslate(BaseTool):
    name = "argos_translate"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "translation"
    provider = "argos_translate"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL
    dependencies = ["python:argostranslate"]
    install_instructions = (
        "Install the optional package with: pip install -r requirements-localization-argos.txt\n"
        "Install the Argos language-pair package(s) required by the route; use the Argos package manager. "
        "Model packages have separate terms and must be reviewed individually."
    )
    agent_skills = ["content-factory-localization"]
    capabilities = ["translate_text", "translate_subtitles", "offline_generation"]
    supports = {"offline": True, "subtitle_timing_preservation": True, "glossary_enforcement": False}
    best_for = ["private/offline translation drafts", "text and SRT subtitle localization", "zero per-request API cost"]
    not_good_for = ["high-stakes legal or medical translation without human review", "guaranteed terminology/glossary enforcement"]
    input_schema = {
        "type": "object", "required": ["source_language", "target_language"],
        "properties": {
            "text": {"type": "string", "description": "Text to translate. Use this or input_path."},
            "input_path": {"type": "string", "description": "Optional SRT file to translate while preserving cue indices and timestamps."},
            "source_language": {"type": "string", "description": "Source language code or BCP-47 locale; required and cannot be auto for Argos."},
            "target_language": {"type": "string", "description": "Target language code or BCP-47 locale."},
            "output_path": {"type": "string", "description": "Optional SRT output path; required when input_path is used."},
        },
        "oneOf": [{"required": ["text"]}, {"required": ["input_path", "output_path"]}],
    }
    output_schema = {"type": "object", "properties": {"translated_text": {"type": "string"}, "source_language": {"type": "string"}, "target_language": {"type": "string"}, "output": {"type": "string"}}}
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1200, vram_mb=0, disk_mb=1500, network_required=False)
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = ["text", "input_path", "source_language", "target_language"]
    side_effects = ["writes translated SRT only when output_path is supplied"]
    user_visible_verification = ["Review meaning, names and terminology against the source", "For SRT, verify cue timing and line breaks in the rendered video"]

    def get_status(self) -> ToolStatus:
        try:
            import argostranslate.translate  # noqa: F401
            return ToolStatus.AVAILABLE
        except ImportError:
            return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if self.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(success=False, error="Argos Translate is not installed. " + self.install_instructions)
        source = _language_code(inputs["source_language"])
        target = _language_code(inputs["target_language"])
        if source == "auto" or source == target:
            return ToolResult(success=False, error="Provide distinct, explicit source_language and target_language codes; Argos does not detect the source language.")
        started = time.time()
        try:
            import argostranslate.translate as translate

            def convert(text: str) -> str:
                return translate.translate(text, source, target)

            if inputs.get("input_path"):
                if inputs.get("text"):
                    return ToolResult(success=False, error="Use either text or input_path, not both.")
                source_path = Path(inputs["input_path"])
                if source_path.suffix.lower() != ".srt" or not source_path.is_file():
                    return ToolResult(success=False, error="input_path must be an existing .srt file.")
                output_path = Path(inputs["output_path"])
                original = source_path.read_text(encoding="utf-8-sig")
                translated_blocks = []
                for block in re.split(r"(\n\s*\n)", original):
                    if not block or block.isspace():
                        translated_blocks.append(block)
                        continue
                    match = _SRT_BLOCK.fullmatch(block)
                    if not match:
                        return ToolResult(success=False, error="Could not parse an SRT cue; source file was left unchanged.")
                    translated_blocks.append(match.group("header") + convert(match.group("body").strip()) + match.group("tail"))
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("".join(translated_blocks), encoding="utf-8")
                data = {"provider": self.provider, "source_language": source, "target_language": target, "output": str(output_path), "subtitle_timing_preserved": True}
                return ToolResult(success=True, data=data, artifacts=[str(output_path)], cost_usd=0.0, duration_seconds=round(time.time() - started, 2), model="argos-translate")
            if not inputs.get("text"):
                return ToolResult(success=False, error="Provide non-empty text or an SRT input_path and output_path.")
            translated = convert(inputs["text"])
            return ToolResult(success=True, data={"provider": self.provider, "source_language": source, "target_language": target, "translated_text": translated}, cost_usd=0.0, duration_seconds=round(time.time() - started, 2), model="argos-translate")
        except Exception as exc:
            return ToolResult(success=False, error=f"Argos translation failed: {exc}. Confirm the requested language pair is installed.")
