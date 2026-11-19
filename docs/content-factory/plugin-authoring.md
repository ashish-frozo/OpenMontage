# Add a library adapter

Create a separate Python package, install it in the MCP environment, and expose
an entry point. Its code is trusted local code; a manifest is not a sandbox.

```toml
[project.entry-points."openmontage.content_plugins"]
my_library = "my_adapter:MyPlugin"
```

Implement `content_factory.registry.Plugin`:

```python
from content_factory.registry import Plugin
from content_factory.models import PluginManifest, Operation

class MyPlugin(Plugin):
    manifest = PluginManifest(
        id="my-library", version="1.0.0", plugin_api_version=1,
        description="Describe this library's actual capabilities.",
        best_for=["diagram animation"], limitations=["no speech synthesis"],
    )

    def operations(self):
        return [Operation(
            id="render", capability="diagram_animation",
            description="Render a diagram scene from a validated source file.",
            provider="my-library", runtime="local", version="1.0.0",
            stages=["assets"],
            input_schema={
                "type": "object", "additionalProperties": False,
                "required": ["input_path", "output_path"],
                "properties": {
                    "input_path": {"type": "string"},
                    "output_path": {"type": "string"},
                    "fps": {"type": "integer", "minimum": 1, "default": 30},
                },
            },
            input_artifacts=["diagram_source"], output_artifacts=["video_clip"],
            instructions=["production"],
        )]

    def health(self, operation):
        # Check the real executable/version/models, not just whether this adapter exists.
        return {"status": "unavailable", "network_required": False,
                "setup": "Install and configure the library runtime."}

    def instruction(self, name):
        if name != "production":
            raise ValueError("Unknown instruction")
        return "Author a scene from the approved scene plan, preview it, then render."

    def execute(self, operation, params):
        # Delegate to a registered BaseTool wrapper; implement this before advertising available.
        raise NotImplementedError("Implement the library's BaseTool adapter")
```

The `execute` result follows the ToolResult shape: `success`, `data`, `artifacts`,
`error`, `cost_usd`, and optional timing/model/seed metadata. For production tools,
implement a `BaseTool` and register it with OpenMontage's registry. Return
`dataclasses.asdict(tool.execute(params))` from the plugin. Declare the associated
`native_tool` in the operation and grant it in the appropriate pipeline's
`tools_available`. An operation without `native_tool` instead requires a pipeline
with `extensions.custom_tools: true` and a matching `stages` entry.

Expose all supported native parameters in the JSON schema, including nested
objects, enums, limits and descriptions. Defaults are descriptive: your adapter
must apply them. Use argument arrays rather than shell interpolation. Write every
artifact under the supplied project output path. Do not run an upstream library's
installer or update code during `health` or `operations`.

Optional methods: `estimate(operation, params)` returns a nonnegative USD estimate;
`styles()` returns style records with `id` and `instruction`. Use a pinned external
environment/container/service for incompatible Python/Node dependencies. Plugins
must be importable by detached workers in the same environment as the MCP server.

After installation and server restart, the plugin automatically appears in
`factory_plugins` and its operations in `factory_operations`. Invalid/duplicate
plugins appear in discovery errors without hiding healthy adapters. The calling
AI reads the new descriptions/instructions and can choose the adapter without
adding routing keywords or changing MCP tools.

Before enabling it, test native schema validation, unavailable dependencies,
accurate artifacts, nonzero exits, timeout/cancellation and repeated submissions.
