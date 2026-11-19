"""Optional Lemo renderer implementing the standard OpenMontage tool contract."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from tools.base_tool import BaseTool, ToolResult, ToolStatus


class LemoRender(BaseTool):
    name = "lemo_render"
    provider = "lemo"
    capability = "procedural_animation"
    version = "1.0.0"
    best_for = ["code-authored Canvas/WebGL scenes", "illustrated explainers", "stylized short films"]
    not_good_for = ["automatic text replacement in demo films", "photorealistic generated footage"]
    install_instructions = "Install a pinned lemo-opuscar checkout with its core dependencies; set LEMO_OPUSCAR_HOME. Requires Node >=20, FFmpeg >=7 and the upstream browser setup."
    input_schema = {
        "type": "object", "additionalProperties": False,
        "required": ["workspace", "output_path"],
        "properties": {
            "workspace": {"type": "string", "description": "Authored scene directory containing index.html, inside the project."},
            "output_path": {"type": "string", "description": "MP4 file for render; directory for preview."},
            "mode": {"type": "string", "enum": ["render", "preview", "readcheck"], "default": "render"},
            "fps": {"type": "integer", "minimum": 1, "maximum": 120, "default": 24},
            "width": {"type": "integer", "minimum": 64, "maximum": 7680, "multipleOf": 2, "default": 1920},
            "height": {"type": "integer", "minimum": 64, "maximum": 7680, "multipleOf": 2, "default": 1080},
            "workers": {"type": "integer", "minimum": 1, "maximum": 6, "default": 3},
            "times": {"type": "array", "minItems": 1, "maxItems": 100, "items": {"type": "number", "minimum": 0}, "default": [0]},
            "query": {"type": "string", "default": "", "description": "URL query parameters supplied to the authored page."},
            "latin_cps": {"type": "number", "exclusiveMinimum": 0, "default": 15},
            "cjk_cps": {"type": "number", "exclusiveMinimum": 0, "default": 4.5},
            "readcheck_step": {"type": "number", "exclusiveMinimum": 0, "default": 0.04},
            "readcheck_padding": {"type": "number", "minimum": 0, "default": 1.5},
            "readcheck_minimum": {"type": "number", "minimum": 0, "default": 1.5},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 86400, "default": 1800},
            "webgl_backend": {"type": "string", "enum": ["default", "metal", "swiftshader"], "default": "default"},
        },
    }

    @property
    def home(self):
        return Path(os.environ.get("LEMO_OPUSCAR_HOME", "~/lemo-opuscar")).expanduser().resolve()

    def get_status(self):
        if not all(shutil.which(x) for x in ("node", "ffmpeg")):
            return ToolStatus.UNAVAILABLE
        if not all((self.home / p).exists() for p in ("core/render/video.mjs", "node_modules/playwright-core", "node_modules/three")):
            return ToolStatus.UNAVAILABLE
        try:
            node = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5, check=True).stdout
            ffmpeg = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5, check=True).stdout
            node_version = re.search(r"v(\d+)", node)
            ffmpeg_version = re.search(r"ffmpeg version (\d+)", ffmpeg)
            if not node_version or int(node_version[1]) < 20 or not ffmpeg_version or int(ffmpeg_version[1]) < 7:
                return ToolStatus.UNAVAILABLE
        except (OSError, subprocess.SubprocessError):
            return ToolStatus.UNAVAILABLE
        try:
            subprocess.run(["node", "--input-type=module", "-e",
                "import {chromium} from 'playwright-core'; const b=await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROME||undefined,timeout:5000}); await b.close();"],
                cwd=self.home, capture_output=True, timeout=8, check=True)
        except (OSError, subprocess.SubprocessError):
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE

    def command(self, params):
        workspace = Path(params["workspace"]).resolve()
        if not (workspace / "index.html").is_file():
            raise ValueError("Author workspace/index.html with window.READY, window.DUR and window.render(t) first.")
        mode = params.get("mode", "render")
        script = {"render": "video", "preview": "still", "readcheck": "readcheck"}[mode]
        cmd = ["node", str(self.home / f"core/render/{script}.mjs"), str(workspace)]
        output = Path(params["output_path"]).resolve()
        if mode == "preview":
            cmd.extend(str(t) for t in params.get("times", [0]))
        if mode != "readcheck":
            cmd += ["--out", str(output)]
        if mode == "render":
            cmd += ["--fps", str(params.get("fps", 24)), "--workers", str(params.get("workers", 3))]
        if mode == "readcheck":
            for key, flag, default in [("latin_cps", "--latin-cps", 15), ("cjk_cps", "--cjk-cps", 4.5), ("readcheck_step", "--step", .04), ("readcheck_padding", "--pad", 1.5), ("readcheck_minimum", "--min", 1.5)]:
                cmd += [flag, str(params.get(key, default))]
        cmd += ["--size", f"{params.get('width', 1920)}x{params.get('height', 1080)}"]
        if params.get("query"):
            cmd += ["--q", params["query"]]
        return cmd

    def execute(self, inputs):
        import jsonschema
        jsonschema.validate(inputs, self.input_schema)
        cmd = self.command(inputs)
        Path(inputs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "LEMO_ANGLE": inputs.get("webgl_backend", "default")}
        completed = subprocess.run(cmd, cwd=self.home, env=env, timeout=inputs.get("timeout_seconds", 1800), check=False)
        output = Path(inputs["output_path"])
        check = inputs.get("mode") == "readcheck"
        success = completed.returncode == 0 and (check or output.exists())
        return ToolResult(success=success, data={"output_path": str(output), "mode": inputs.get("mode", "render")},
                          artifacts=[] if check or not success else [str(output)], error=None if success else f"Lemo failed (exit {completed.returncode}); inspect job log.")

