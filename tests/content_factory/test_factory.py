"""Contract and process tests; no paid providers or model downloads."""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from content_factory.models import Operation, PluginManifest, ProjectConfig, RoutePlan
from content_factory.registry import Plugin, Registry
from content_factory.service import Factory


class ExamplePlugin(Plugin):
    manifest = PluginManifest(id="example", version="1.0", description="Fixture external adapter")
    available = True

    def operations(self):
        return [Operation(id="draw", capability="drawing", description="Draw test scene", provider="example", runtime="local", version="1",
                          native_tool="math_animate", input_schema={"type": "object", "required": ["value"], "additionalProperties": False,
                          "properties": {"value": {"type": "integer", "minimum": 0}, "model": {"type": "string"}, "output_path": {"type": "string"}}})]

    def health(self, operation):
        return {"status": "available" if self.available else "unavailable", "network_required": False}

    def execute(self, operation, params):
        return {"success": True, "data": params}


@pytest.fixture
def factory(tmp_path):
    return Factory(Registry([ExamplePlugin()]), tmp_path)


def create(factory, **config):
    return factory.create("test-film", "Test", "animation", ProjectConfig(**config))


def plan(operation="example:draw", **params):
    return RoutePlan(request="A diagram", steps=[{"id": "scene", "stage": "assets", "operation": operation,
                       "params": {"value": 2, **params}, "reason": "Matches the requested diagram"}])


def test_extensible_registry_duplicate_isolation():
    registry = Registry([ExamplePlugin(), ExamplePlugin()])
    assert list(registry.operations) == ["example:draw"]
    assert "Duplicate" in registry.errors[0]["error"]


def test_defaults_locks_and_revision(factory):
    create(factory, native_defaults={"example:draw": {"value": 1}}, locked_params={"example:draw": {"model": "fixed"}})
    result = factory.save_plan("test-film", plan())
    assert result["steps"][0]["params"] == {"value": 2, "model": "fixed"}
    with pytest.raises(ValueError, match="locked"):
        factory.validate_plan("test-film", plan(model="different"))
    factory.configure("test-film", ProjectConfig(), 1)
    with pytest.raises(ValueError, match="Configuration changed"):
        factory.configure("test-film", ProjectConfig(), 1)
    with pytest.raises(ValueError, match="stale"):
        factory.submit("test-film", result["plan_id"], "scene", "once", "User approved")


def test_native_schema_and_unknown_config(factory):
    create(factory)
    with pytest.raises(Exception, match="minimum"):
        factory.validate_plan("test-film", plan(value=-1))
    with pytest.raises(Exception, match="Additional properties"):
        factory.validate_plan("test-film", plan(typo=True))
    with pytest.raises(ValidationError):
        ProjectConfig(unknown_setting=True)


def test_route_constraints_and_availability(factory):
    create(factory, routing={"excluded_plugins": ["example"]})
    with pytest.raises(ValueError, match="disallowed"):
        factory.validate_plan("test-film", plan())
    factory.configure("test-film", ProjectConfig(routing={"mode": "directed"}), 1)
    with pytest.raises(ValueError, match="explicit pin"):
        factory.validate_plan("test-film", plan())
    factory.configure("test-film", ProjectConfig(routing={"mode": "directed", "pinned_operations": {"assets": "example:draw"}}), 2)
    assert factory.validate_plan("test-film", plan())["steps"]
    factory.registry.plugins["example"].available = False
    with pytest.raises(ValueError, match="unavailable"):
        factory.validate_plan("test-film", plan())


def test_paths_dependencies_and_stage_permissions(factory, tmp_path):
    create(factory)
    with pytest.raises(ValueError, match="inside"):
        factory.validate_plan("test-film", plan(output_path=str(tmp_path / "escape.mp4")))
    with pytest.raises(ValueError):
        factory.project("../escape")
    bad = plan()
    bad.steps[0].depends_on = ["missing"]
    with pytest.raises(ValueError, match="dependencies"):
        factory.validate_plan("test-film", bad)
    bad = plan()
    bad.steps[0].stage = "research"
    with pytest.raises(ValueError, match="not permitted"):
        factory.validate_plan("test-film", bad)
    (factory.project("test-film") / "assets/link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        factory.validate_plan("test-film", plan(output_path=str(factory.project("test-film") / "assets/link/escape.mp4")))


def test_submit_requires_approval_and_predecessors(factory):
    create(factory)
    result = factory.save_plan("test-film", plan())
    with pytest.raises(ValueError, match="approval"):
        factory.submit("test-film", result["plan_id"], "scene", "once")
    with pytest.raises(ValueError, match="predecessor research"):
        factory.submit("test-film", result["plan_id"], "scene", "once", "User approved")


def test_checkpoint_preserves_pipeline_gate(factory):
    from tests.contracts.test_phase0_contracts import sample_artifact
    create(factory)
    factory.checkpoint("test-film", "research", "completed", {"research_brief": sample_artifact("research_brief")})
    with pytest.raises(ValueError, match="GATE VIOLATION"):
        factory.checkpoint("test-film", "proposal", "completed", {"proposal_packet": sample_artifact("proposal_packet")})
    assert factory.stage_context("test-film")["stage"] == "proposal"


def test_submission_idempotency_concurrency_and_config_snapshot(factory, monkeypatch):
    from tests.contracts.test_phase0_contracts import sample_artifact
    create(factory, max_concurrent_jobs=1)
    for stage, artifact in [("research", "research_brief"), ("proposal", "proposal_packet"), ("script", "script"), ("scene_plan", "scene_plan")]:
        factory.checkpoint("test-film", stage, "completed", {artifact: sample_artifact(artifact)}, "User approved this fixture")
    saved = factory.save_plan("test-film", plan())
    class Process:
        pid = os.getpid()
    launches = []
    def launch(*args, **kwargs):
        launches.append(args)
        return Process()
    monkeypatch.setattr("content_factory.service.subprocess.Popen", launch)
    job = factory.submit("test-film", saved["plan_id"], "scene", "key", "Approved")
    repeat = factory.submit("test-film", saved["plan_id"], "scene", "key", "Approved")
    assert repeat["job_id"] == job["job_id"]
    assert len(launches) == 1
    with pytest.raises(ValueError, match="Concurrent"):
        factory.submit("test-film", saved["plan_id"], "scene", "other", "Approved")
    other = factory.save_plan("test-film", plan(value=3))
    with pytest.raises(ValueError, match="Idempotency"):
        factory.submit("test-film", other["plan_id"], "scene", "key", "Approved")
    factory.configure("test-film", ProjectConfig(timeout_seconds=60), 1)
    replay = factory.submit("test-film", saved["plan_id"], "scene", "key")
    assert replay["request"]["timeout_seconds"] == 1800
    assert factory.cancel("test-film", job["job_id"])["status"] == "cancelling"


def test_network_and_estimate_constraints(factory):
    create(factory, routing={"allow_network": False})
    plugin = factory.registry.plugins["example"]
    plugin.health = lambda op: {"status": "available", "network_required": True}
    with pytest.raises(ValueError, match="network"):
        factory.validate_plan("test-film", plan())
    factory.configure("test-film", ProjectConfig(max_job_estimate_usd=.5), 1)
    plugin.estimate = lambda op, params: 1.0
    with pytest.raises(ValueError, match="exceeds"):
        factory.validate_plan("test-film", plan())


def test_supervisor_timeout_and_reconciliation(factory, monkeypatch):
    from content_factory.worker import supervise
    create(factory)
    logs = factory.project("test-film") / "artifacts/factory-jobs"
    logs.mkdir()
    with factory.db("test-film") as db:
        db.execute("INSERT INTO jobs VALUES ('timeout', 'timeout', 'hash', 'queued', ?, NULL, NULL)", (json.dumps({"timeout_seconds": 0}),))
    class Child:
        pid = 123456
        def poll(self):
            return None
        def wait(self, timeout=None):
            return 0
    signals = []
    monkeypatch.setattr("content_factory.worker.subprocess.Popen", lambda *a, **k: Child())
    monkeypatch.setattr("content_factory.worker.os.killpg", lambda pid, sig: signals.append((pid, sig)))
    supervise(factory.root, "test-film", "timeout")
    assert factory.job("test-film", "timeout")["status"] == "timed_out"
    assert len(signals) == 2
    with factory.db("test-film") as db:
        db.execute("INSERT INTO jobs VALUES ('lost', 'lost', 'hash', 'running', '{}', NULL, 123456)")
    def gone(*args):
        raise ProcessLookupError()
    monkeypatch.setattr("content_factory.service.os.kill", gone)
    assert factory.reconcile("test-film", "lost")["status"] == "interrupted"


def test_mcp_schema_and_source_access(factory):
    from content_factory.server import build_server
    create(factory)
    async def run():
        server = build_server(factory)
        tools = {t.name: t for t in await server.list_tools()}
        assert "factory_submit_job" in tools
        assert "config" in tools["factory_configure_project"].inputSchema["$defs"]["ConfigureProject"]["properties"]
        result = await server.call_tool("factory_write_workspace_file", {"project_id": "test-film", "relative_path": "scene/index.html", "content": "<canvas/>"})
        assert (factory.project("test-film") / "workspaces/scene/index.html").read_text() == "<canvas/>"
        with pytest.raises(Exception):
            await server.call_tool("factory_write_workspace_file", {"project_id": "test-film", "relative_path": "../project.json", "content": "{}"})
    asyncio.run(run())


def test_lemo_command_configuration(tmp_path):
    from content_factory.adapters.lemo import LemoRender
    (tmp_path / "index.html").write_text("<canvas/>")
    cmd = LemoRender().command({"workspace": str(tmp_path), "output_path": str(tmp_path / "out.mp4"), "fps": 30, "width": 1080, "height": 1920, "workers": 2, "query": "title=a;echo unsafe"})
    assert cmd[cmd.index("--size") + 1] == "1080x1920"
    assert cmd[cmd.index("--q") + 1] == "title=a;echo unsafe"
    assert cmd[cmd.index("--fps") + 1] == "30"


def test_real_worker_render_and_persistent_result(tmp_path):
    """Exercise the subprocess boundary using a tiny, synthetic local FFmpeg clip."""
    from content_factory.adapters.openmontage import OpenMontage
    factory = Factory(Registry([OpenMontage()]), tmp_path)
    create(factory)
    project = factory.project("test-film")
    source, target = project / "assets/source.mp4", project / "renders/cut.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=10", "-t", "0.5", "-pix_fmt", "yuv420p", str(source)], check=True)
    _, op = factory.registry.resolve("openmontage:video_trimmer")
    data = {"timeout_seconds": 30, "step": {"operation": "openmontage:video_trimmer", "plugin_version": "1.0.0", "operation_version": op.version,
            "params": {"operation": "cut", "input_path": str(source), "output_path": str(target), "start_seconds": 0, "end_seconds": .3}}}
    logs = project / "artifacts/factory-jobs"
    logs.mkdir()
    with factory.db("test-film") as db:
        db.execute("INSERT INTO jobs VALUES ('job', 'key', 'fingerprint', 'queued', ?, NULL, NULL)", (json.dumps(data),))
    process = subprocess.run([sys.executable, "-m", "content_factory.worker", str(tmp_path), "test-film", "job"], capture_output=True, timeout=40)
    assert process.returncode == 0, process.stderr.decode()
    reconnected = Factory(Registry([]), tmp_path)
    result = reconnected.job("test-film", "job")
    assert result["status"] == "completed", result
    assert target.stat().st_size > 0


def test_stdio_transport(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def run():
        launcher = Path(__file__).resolve().parents[2] / "scripts/content_factory_mcp.py"
        parameters = StdioServerParameters(command=sys.executable, args=[str(launcher), "--projects-dir", str(tmp_path)], cwd=str(tmp_path))
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert any(t.name == "factory_config_schema" for t in tools.tools)
                result = await session.call_tool("factory_plugins", {})
                assert not result.isError
                assert "lemo" in str(result)
                result = await session.call_tool("factory_operation", {"operation": "lemo:render"})
                assert not result.isError
                assert "webgl_backend" in str(result)
                result = await session.call_tool("factory_config_schema", {})
                assert "locked_params" in str(result)
                result = await session.call_tool("factory_projects", {})
                assert not result.isError
    asyncio.run(run())
