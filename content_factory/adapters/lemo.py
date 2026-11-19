"""Lemo styles and rendering adapter for the content factory."""
from dataclasses import asdict
from pathlib import Path

from content_factory.models import Operation, PluginManifest
from content_factory.registry import Plugin
from tools.video.lemo_render import LemoRender


class Lemo(Plugin):
    manifest = PluginManifest(id="lemo", version="1.0.0", description="Lemo-Opuscar styles and deterministic Canvas/WebGL rendering.", best_for=LemoRender.best_for, limitations=LemoRender.not_good_for)

    def __init__(self):
        self.tool = LemoRender()
        from tools.tool_registry import registry
        registry.register(self.tool)

    def operations(self):
        return [Operation(id="render", capability=self.tool.capability, description="Render, preview or check an authored Lemo page; does not write the scene for you.",
                          provider="lemo", runtime="local", version=self.manifest.version, input_schema=self.tool.input_schema,
                          best_for=self.manifest.best_for, limitations=self.manifest.limitations,
                          input_artifacts=["authored_web_scene"], output_artifacts=["video_clip", "preview_image", "readability_report"],
                          stages=["assets"], native_tool="lemo_render", instructions=["production", "DIRECTOR.md", "TECHNIQUE.md", "core/README.md"])]

    def health(self, operation):
        return {"status": self.tool.get_status().value, "setup": self.tool.install_instructions, "network_required": False,
                "note": "Checks core files, commands and a headless browser launch; GPU and scene assets are validated at render time. Authored pages must self-host assets for offline runs."}

    def execute(self, operation, params):
        return asdict(self.tool.execute(params))

    def instruction(self, name):
        if name == "production":
            return (Path(__file__).parents[1] / "skills/lemo.md").read_text()
        if name not in {"DIRECTOR.md", "TECHNIQUE.md", "core/README.md"} and not (name.startswith("styles/") and name.endswith("/STYLE.md")):
            raise ValueError("Unknown Lemo instruction")
        path = (self.tool.home / name).resolve()
        if not path.is_relative_to(self.tool.home):
            raise ValueError("Instruction outside Lemo checkout")
        return path.read_text()

    def styles(self):
        return [{"id": p.parent.name, "instruction": f"styles/{p.parent.name}/STYLE.md"} for p in sorted((self.tool.home / "styles").glob("*/STYLE.md"))]
