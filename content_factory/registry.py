"""Discover trusted installed plugins; never install code from a user prompt."""
from __future__ import annotations

from abc import ABC, abstractmethod
from importlib.metadata import entry_points
from typing import Any

from content_factory.models import Operation, PluginManifest


class Plugin(ABC):
    manifest: PluginManifest

    @abstractmethod
    def operations(self) -> list[Operation]: ...

    @abstractmethod
    def health(self, operation: str) -> dict[str, Any]: ...

    @abstractmethod
    def execute(self, operation: str, params: dict[str, Any]) -> dict[str, Any]: ...

    def estimate(self, operation: str, params: dict[str, Any]) -> float:
        return 0.0

    def instruction(self, name: str) -> str:
        raise ValueError(f"Unknown instruction: {name}")


class Registry:
    def __init__(self, plugins: list[Plugin] | None = None):
        self.plugins: dict[str, Plugin] = {}
        self.errors: list[dict] = []
        if plugins is None:
            from content_factory.adapters.openmontage import OpenMontage
            from content_factory.adapters.lemo import Lemo
            plugins = [OpenMontage(), Lemo()]
            for entry in entry_points(group="openmontage.content_plugins"):
                try:
                    plugins.append(entry.load()())
                except Exception as exc:
                    self.errors.append({"plugin": entry.name, "error": str(exc)})
        self.operations: dict[str, Operation] = {}
        for plugin in plugins:
            try:
                manifest = PluginManifest.model_validate(plugin.manifest)
                if manifest.id in self.plugins:
                    raise ValueError(f"Duplicate plugin id: {manifest.id}")
                ops = [Operation.model_validate(op) for op in plugin.operations()]
                if len({op.id for op in ops}) != len(ops):
                    raise ValueError("Duplicate operation id")
                import jsonschema
                for op in ops:
                    jsonschema.Draft202012Validator.check_schema(op.input_schema)
                self.plugins[manifest.id] = plugin
                self.operations.update({f"{manifest.id}:{op.id}": op for op in ops})
            except Exception as exc:
                self.errors.append({"plugin": getattr(getattr(plugin, "manifest", None), "id", type(plugin).__name__), "error": str(exc)})

    def resolve(self, name: str) -> tuple[Plugin, Operation]:
        if name not in self.operations:
            raise ValueError(f"Unknown operation {name!r}; call factory_operations first.")
        return self.plugins[name.split(":", 1)[0]], self.operations[name]
