"""Local MCP server with discoverable native configuration schemas."""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from content_factory.motion import MotionPlan
from lib.creator import RevisionRequest, RevisionEdit
from content_factory.models import CustomerProfile, Model, Page, ProjectConfig, RoutePlan, paginate
from content_factory.service import Factory, identifier
from lib.paths import REPO_ROOT
from lib.pipeline_loader import list_pipelines, load_pipeline


def read_production_guide() -> str:
    """Read the canonical guide via the advertised skills path, with legacy fallback."""
    root = REPO_ROOT.resolve()
    for candidate in (root / "skills/guide.md", root / "AGENT_GUIDE.md"):
        try:
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise ValueError("Production guide resolves outside the OpenMontage repository")
            content = resolved.read_text(encoding="utf-8")
            if content.strip():
                return content
        except FileNotFoundError:
            continue
    raise FileNotFoundError(
        f"OpenMontage production guide is missing. Expected {root / 'skills/guide.md'} "
        f"or {root / 'AGENT_GUIDE.md'}; refusing to start a production workflow without its approval gates."
    )


def _trim_untrusted_research(result: dict) -> dict:
    data = (result.get("result") or {}).get("data", {}) if isinstance(result.get("result"), dict) else {}
    for source in data.get("sources", [data]) if isinstance(data, dict) else []:
        if isinstance(source, dict) and source.get("trust") == "untrusted_source_content" and len(source.get("text", "")) > 8000:
            source["text"] = source["text"][:8000]
            source["text_truncated"] = True
            source["next_action"] = "Read remaining source text through factory_read_project_file using output_path."
    return result


class OperationQuery(Page):
    plugin: str | None = Field(default=None, description="Plugin id; omit to search every installed adapter.")
    capability: str | None = Field(default=None, description="Exact capability family.")
    query: str = Field(default="", description="Text filter across names, descriptions and strengths; the AI ranks creative fit.")
    include_schemas: bool = False
    check_health: bool = False


class CreateProject(Model):
    project_id: str
    title: str
    pipeline: str
    config: ProjectConfig = Field(default_factory=ProjectConfig)


class ConfigureProject(Model):
    project_id: str
    expected_revision: int = Field(ge=1)
    config: ProjectConfig


class SaveCustomerProfile(Model):
    profile_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,119}$")
    profile: CustomerProfile
    expected_revision: int | None = Field(default=None, ge=1, description="Omit only when creating a new profile; provide the current revision to update it.")


class PlanInput(Model):
    project_id: str
    plan: RoutePlan


class CheckpointInput(Model):
    project_id: str
    stage: str
    status: Literal["in_progress", "awaiting_human", "completed", "failed"]
    artifacts: dict[str, Any]
    approval_evidence: str | None = Field(default=None, description="Actual user approval statement; omit unless the user approved this gate.")
    review: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class SubmitInput(Model):
    project_id: str
    plan_id: str
    step_id: str
    idempotency_key: str = Field(description="Stable unique identifier for this execution. Reuse on transport retries.")
    approval_evidence: str | None = None


def build_server(factory=None, *, server_class=FastMCP, server_options=None, download_signer=None):
    with contextlib.redirect_stdout(sys.stderr):
        factory = factory or Factory()
    routing = (Path(__file__).parent / "skills/routing.md").read_text()
    mcp = server_class("content_factory_mcp", instructions=routing, **(server_options or {}))
    read = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
    write = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    @mcp.resource("factory://guide")
    def guide() -> str:
        """OpenMontage production rules and MCP routing instructions."""
        return routing + "\n\n" + read_production_guide()

    @mcp.prompt()
    def create_content(request: str) -> str:
        """Start an agent-directed content production with dynamic plugin selection."""
        return routing + "\n\n" + read_production_guide() + "\n\nUser request:\n" + request

    @mcp.resource("factory://skills/localization")
    def localization_skill() -> str:
        """Language localization, translation, caption and dubbing guidance."""
        return (Path(__file__).parent / "skills/localization.md").read_text()

    @mcp.tool(annotations=read)
    def factory_local_voices(engine: Literal["kokoro", "chatterbox"] = "kokoro") -> dict:
        """List installed local voices/model variants and readiness without loading speech models."""
        from lib.local_tts import model_dir, health
        if engine == "kokoro":
            return {"engine":engine, "health":health(engine), "voices":[{"id":p.stem,"language_code":p.stem[0]} for p in sorted((model_dir(engine)/"voices").glob("*.pt"))],
                    "note":"Japanese/Chinese require optional G2P dependencies. Prefer a tested language; native errors identify missing resources."}
        return {"engine":engine,"variants":[{"id":v, **health(engine,v)} for v in ("english","multilingual")],
                "voices":[{"id":"default","description":"Omit reference_audio_path for built-in speaker"}],
                "reference_voice":"Provide a clean 3–30 second local recording in reference_audio_path."}

    @mcp.tool(annotations=read)
    def factory_review_scene_plan(scene_plan: dict) -> dict:
        """Check shot timing, story intent and declared continuity; returns a fingerprint for safe revisions."""
        from lib.creator import review_scene_plan
        return review_scene_plan(scene_plan)

    @mcp.tool(annotations=read)
    def factory_revision_plan(params: RevisionRequest) -> dict:
        """Preview precise shot changes with locks, timestamped notes and selective rerender impact. Does not apply changes or bypass approvals."""
        from lib.creator import revision_plan
        return revision_plan(params)

    @mcp.tool(annotations=read)
    def factory_preview_revision(project_id: str, params: RevisionEdit) -> dict:
        """Preview changes against the saved scene plan. Send only edits and the current fingerprint; the server preserves source data."""
        from lib.creator import revision_plan
        current=json.loads((factory.project(project_id) / "checkpoint_scene_plan.json").read_text())
        persisted=current.get("metadata", {}).get("creator_locks", {})
        locks={sid:sorted(set(persisted.get(sid,[])+params.locks.get(sid,[]))) for sid in set(persisted)|set(params.locks)}
        request=RevisionRequest(scene_plan=current["artifacts"]["scene_plan"], **{**params.model_dump(), "locks":locks})
        return revision_plan(request)

    @mcp.tool(annotations=write)
    def factory_save_revision(project_id: str, params: RevisionEdit) -> dict:
        """Save a locked shot revision, revoke downstream approvals and invalidate routes. Refuses active jobs; requires a new scene-plan review."""
        from content_factory.creator import save_revision
        root=factory.project(project_id)
        current=json.loads((root / "checkpoint_scene_plan.json").read_text())["artifacts"]["scene_plan"]
        return save_revision(factory, project_id, RevisionRequest(scene_plan=current, **params.model_dump()))

    @mcp.tool(annotations=read)
    def factory_motion_scene_schema() -> dict:
        """Get the bounded scene contract for openmontage:motion_scene. No JavaScript authoring needed."""
        from lib.motion_scene import MotionScene, RECIPES, recipe_examples
        return {"schema": MotionScene.model_json_schema(), "recipes": [{"id": k, "library": v[0], "description": v[1], "example": recipe_examples()[k]} for k, v in RECIPES.items()],
                "example": {"objects": [{"id": "sketch", "recipe": "sketch"}]},
                "next_action": "Validate scene, then submit openmontage:motion_scene in the assets stage through a saved route."}

    @mcp.tool(annotations=read)
    def factory_validate_motion_scene(scene: dict) -> dict:
        """Validate scene data with field-level errors; does not render or bypass stage gates."""
        from lib.motion_scene import validate_scene
        return validate_scene(scene)

    @mcp.tool(annotations=read)
    def factory_motion_presets(query: str = "", offset: int = 0, limit: int = 30) -> dict:
        """Browse executable GSAP motions; choose ids then call factory_compile_motion."""
        from content_factory.motion import PRESETS
        return paginate([{"id": p["id"], "category": p["category"]} for p in PRESETS.values()
                         if query.lower() in (p["id"] + " " + p["category"])], Page(offset=offset, limit=limit))

    @mcp.tool(annotations=read)
    def factory_compile_motion(params: MotionPlan) -> dict:
        """Compile named motions into GSAP workspace source. Does not render, bill, or change approval gates."""
        from content_factory.motion import compile_motion
        return compile_motion(params)

    @mcp.tool(annotations=read)
    def factory_plugins() -> dict:
        """List installed plugin manifests and isolated discovery errors; does not install libraries."""
        return {"plugins": [p.manifest.model_dump() for p in factory.registry.plugins.values()], "errors": factory.registry.errors}

    @mcp.tool(annotations={**read, "openWorldHint": True})
    def factory_operations(params: OperationQuery) -> dict:
        """Discover operations across adapters. Return schemas/health on demand; use capabilities to shortlist routes."""
        items = []
        for name, op in factory.registry.operations.items():
            if params.plugin and name.split(":")[0] != params.plugin:
                continue
            if params.capability and op.capability != params.capability:
                continue
            if params.query.lower() not in json.dumps(op.model_dump()).lower():
                continue
            item = {"operation": name, **op.model_dump(exclude=set() if params.include_schemas else {"input_schema", "output_schema"})}
            items.append(item)
        result = paginate(items, params)
        if params.check_health:
            for item in result["items"]:
                plugin, op = factory.registry.resolve(item["operation"])
                try:
                    item["health"] = plugin.health(op.id)
                except Exception as exc:
                    item["health"] = {"status": "unavailable", "error": str(exc)}
        return result

    @mcp.tool(annotations={**read, "openWorldHint": True})
    def factory_operation(operation: str) -> dict:
        """Get every native parameter, defaults, enums, limits, instructions and current health for one plugin:operation."""
        plugin, op = factory.registry.resolve(operation)
        return {"operation": operation, **op.model_dump(), "health": plugin.health(op.id)}

    @mcp.tool(annotations=read)
    def factory_config_schema() -> dict:
        """Discover project configuration and route schemas. Native settings are in factory_operation.input_schema."""
        return {"project": ProjectConfig.model_json_schema(), "route": RoutePlan.model_json_schema(),
                "customer_profile": CustomerProfile.model_json_schema(),
                "precedence": "profile operation_defaults < native_defaults < locked_params < step.params (shallow merge); conflicting overrides of locked_params are rejected",
                "brief": "Planning context consumed by the AI, not automatically injected into renderers."}

    @mcp.tool(annotations=read)
    def factory_customer_profiles(offset: int = 0, limit: int = 30) -> dict:
        """List saved, versioned customer brand profiles for selecting one when creating or configuring a project."""
        return factory.customer_profiles(Page(offset=offset, limit=limit))

    @mcp.tool(annotations=read)
    def factory_customer_profile(profile_id: str) -> dict:
        """Read a customer's current brand, publishing, production, and safety profile and its revision."""
        return factory.customer_profile(profile_id)

    @mcp.tool(annotations=read)
    def factory_customer_profile_history(profile_id: str, offset: int = 0, limit: int = 30) -> dict:
        """Read immutable previous revisions of a customer profile."""
        return factory.customer_profile_history(profile_id, Page(offset=offset, limit=limit))

    @mcp.tool(annotations=write)
    def factory_save_customer_profile(params: SaveCustomerProfile) -> dict:
        """Create a customer profile, or update it with optimistic revision checking; each save is retained in history."""
        return factory.save_customer_profile(params.profile_id, params.profile, params.expected_revision)

    @mcp.tool(annotations=read)
    def factory_pipelines(pipeline: str | None = None) -> dict:
        """List existing production pipelines or retrieve one full manifest, including stages and approval gates."""
        names = list_pipelines()
        if pipeline is not None:
            if pipeline not in names:
                raise ValueError("Unknown pipeline")
            return load_pipeline(pipeline)
        return {"pipelines": [{"id": n, "description": (m := load_pipeline(n)).get("description"), "stability": m.get("stability")} for n in names]}

    @mcp.tool(annotations=read)
    def factory_artifact_schema(name: str | None = None) -> dict:
        """List canonical artifact schema names or retrieve the schema needed to write a valid checkpoint."""
        from schemas.artifacts import ARTIFACT_NAMES, load_schema
        if name is None:
            return {"names": ARTIFACT_NAMES}
        if name not in ARTIFACT_NAMES:
            raise ValueError("Unknown artifact schema")
        return load_schema(name)

    @mcp.tool(annotations={**write, "destructiveHint": True, "idempotentHint": True})
    def factory_write_workspace_file(project_id: str, relative_path: str, content: str) -> dict:
        """Write authored scene source under project/workspaces/. Supports HTML, JS, CSS, JSON, SVG, Markdown and Python. Does not execute it."""
        factory.marker(project_id)
        root = factory.project(project_id) / "workspaces"
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root) or path.suffix not in {".html", ".js", ".mjs", ".css", ".json", ".svg", ".md", ".py", ".tsx", ".ts"}:
            raise ValueError("Use a supported source file inside workspaces/")
        if len(content.encode()) > 1_000_000:
            raise ValueError("Source file limit is 1MB")
        path.parent.mkdir(parents=True, exist_ok=True)
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        temporary.replace(path)
        return {"path": str(path), "bytes": path.stat().st_size}

    @mcp.tool(annotations=read)
    def factory_read_project_file(project_id: str, relative_path: str, offset: int = 0, limit: int = 16000) -> dict:
        """Read a bounded UTF-8 slice of project source or JSON artifacts. Media files are returned as paths by factory_outputs."""
        root = factory.project(project_id)
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root) or path.suffix not in {".json", ".md", ".html", ".css", ".js", ".mjs", ".tsx", ".ts", ".py", ".svg", ".srt"}:
            raise ValueError("Use a text/source file inside the project")
        if offset < 0 or not 1 <= limit <= 32000:
            raise ValueError("Invalid pagination")
        if path.stat().st_size > 2_000_000:
            raise ValueError("File exceeds 2MB text reader limit")
        text = path.read_text()
        return {"text": text[offset:offset+limit], "total_characters": len(text), "next_offset": offset+limit if offset+limit < len(text) else None}

    @mcp.tool(annotations=read)
    def factory_instruction(name: str, plugin: str | None = None) -> str:
        """Read a plugin instruction or repository skill (e.g. meta/reviewer or content-factory-localization). Lemo also accepts styles/<slug>/STYLE.md."""
        if plugin:
            if plugin not in factory.registry.plugins:
                raise ValueError("Unknown plugin")
            return factory.registry.plugins[plugin].instruction(name)
        if name in {
            "hyperframes-core", "skills/hyperframes-core.md",
            "faceless-explainer", "skills/faceless-explainer.md",
        }:
            return factory.registry.plugins["openmontage"].instruction(name)
        if name in {"content-factory-localization", "localization"}:
            return (Path(__file__).parent / "skills/localization.md").read_text()
        root = (REPO_ROOT / "skills").resolve()
        path = (root / f"{name}.md").resolve()
        if not path.is_relative_to(root):
            raise ValueError("Invalid skill path")
        return path.read_text()

    @mcp.tool(annotations=read)
    def factory_styles(plugin: str = "lemo", query: str = "", offset: int = 0, limit: int = 30) -> dict:
        """Browse installed styles and curated OpenMontage style recipes; use factory_style for full recipe details."""
        adapter = factory.registry.plugins.get(plugin)
        if adapter is None:
            raise ValueError("Unknown plugin")
        styles = adapter.styles() if hasattr(adapter, "styles") else []
        return paginate([s for s in styles if query.lower() in json.dumps(s).lower()], Page(offset=offset, limit=limit))

    @mcp.tool(annotations=read)
    def factory_style(style_id: str, plugin: str = "openmontage") -> dict:
        """Get a complete style playbook or curated recipe, including renderer fit and license provenance."""
        adapter = factory.registry.plugins.get(plugin)
        if adapter is None or not hasattr(adapter, "style"):
            raise ValueError("This plugin does not provide style detail lookup")
        return adapter.style(style_id)

    @mcp.tool(annotations=read)
    def factory_motion_resources(query: str = "", offset: int = 0, limit: int = 30) -> dict:
        """Discover curated motion-design skills and renderer template libraries with compatibility and licensing notes."""
        adapter = factory.registry.plugins.get("openmontage")
        resources = adapter.motion_resources() if adapter and hasattr(adapter, "motion_resources") else []
        return paginate([r for r in resources if query.lower() in json.dumps(r).lower()], Page(offset=offset, limit=limit))

    @mcp.tool(annotations=write)
    def factory_create_project(params: CreateProject) -> dict:
        """Create an OpenMontage project with validated configuration. Returns the Backlot command for the agent to open."""
        return factory.create(params.project_id, params.title, params.pipeline, params.config)

    @mcp.tool(annotations=read)
    def factory_project(project_id: str) -> dict:
        """Get project identity, configuration revision and the next stage's instructions and checkpoint."""
        revision, config = factory.settings(project_id)
        return {"project": factory.marker(project_id), "revision": revision, "config": config.model_dump(),
                "customer_profile": factory.customer_profile_for_project(project_id), "next_stage": factory.stage_context(project_id)}

    @mcp.tool(annotations=read)
    def factory_projects(offset: int = 0, limit: int = 30) -> dict:
        """List factory-managed projects for reconnecting and resuming previous work."""
        items = []
        for path in sorted(factory.root.glob("*/project.json")):
            if (path.parent / "factory.sqlite3").is_file() and path.resolve().is_relative_to(factory.root):
                items.append(json.loads(path.read_text()))
        return paginate(items, Page(offset=offset, limit=limit))

    @mcp.tool(annotations=read)
    def factory_routes(project_id: str, plan_id: str | None = None, offset: int = 0, limit: int = 30) -> dict:
        """Retrieve an immutable saved route, or page through saved route ids and requests."""
        page = Page(offset=offset, limit=limit)
        with factory.db(project_id) as db:
            if plan_id:
                row = db.execute("SELECT data FROM plans WHERE id=?", (identifier(plan_id),)).fetchone()
                if row is None:
                    raise ValueError("Unknown plan")
                return {"plan_id": plan_id, **json.loads(row[0])}
            total = db.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
            rows = db.execute("SELECT id,revision,data FROM plans ORDER BY rowid DESC LIMIT ? OFFSET ?", (page.limit, page.offset)).fetchall()
        return {"items": [{"plan_id": r["id"], "config_revision": r["revision"], "request": json.loads(r["data"])["request"]} for r in rows],
                "total": total, "next_offset": page.offset+page.limit if page.offset+page.limit < total else None}

    hosted_jobs = getattr(factory, "hosted_jobs", None)
    if hosted_jobs is not None:
        @mcp.tool(annotations=read)
        async def factory_jobs(project_id: str, status: str | None = None, offset: int = 0, limit: int = 30) -> dict:
            """List durable workspace job ids and states; read full results through factory_job_status."""
            return await factory.hosted_jobs(project_id, status, offset, limit)
    else:
        @mcp.tool(annotations=read)
        def factory_jobs(project_id: str, status: str | None = None, offset: int = 0, limit: int = 30) -> dict:
            """List saved job ids and states; optional exact state filter. Read full results through factory_job_status."""
            page = Page(offset=offset, limit=limit)
            with factory.db(project_id) as db:
                total = db.execute("SELECT COUNT(*) FROM jobs WHERE (? IS NULL OR status=?)", (status, status)).fetchone()[0]
                rows = db.execute("SELECT id,status FROM jobs WHERE (? IS NULL OR status=?) ORDER BY rowid DESC LIMIT ? OFFSET ?", (status, status, page.limit, page.offset)).fetchall()
            return {"items": [{"job_id": r["id"], "status": r["status"]} for r in rows], "total": total,
                    "next_offset": page.offset+page.limit if page.offset+page.limit < total else None}

    @mcp.tool(annotations=read)
    def factory_project_activity(project_id: str, offset: int = 0, limit: int = 30) -> dict:
        """Show a compact, paginated project timeline of saved jobs and pipeline checkpoints for resuming or reviewing work."""
        from lib.checkpoint import read_checkpoint
        from lib.pipeline_loader import get_stage_order, load_pipeline

        page = Page(offset=offset, limit=limit)
        marker = factory.marker(project_id)
        activity = []
        manifest = load_pipeline(marker["pipeline_type"])
        for stage in get_stage_order(manifest):
            checkpoint = read_checkpoint(factory.root, project_id, stage)
            if checkpoint:
                activity.append({"type": "checkpoint", "stage": stage,
                                 "status": checkpoint.get("status"),
                                 "human_approved": checkpoint.get("human_approved", False),
                                 "artifacts": sorted((checkpoint.get("artifacts") or {}).keys())})
        with factory.db(project_id) as db:
            jobs = db.execute("SELECT id,status,data,result FROM jobs ORDER BY rowid DESC").fetchall()
        for job in jobs:
            data = json.loads(job["data"])
            step = data.get("step", {})
            activity.append({"type": "job", "job_id": job["id"], "status": job["status"],
                             "stage": step.get("stage"), "operation": step.get("operation"),
                             "result_available": bool(job["result"])})
        # Checkpoints first in pipeline order, then newest-first job rows.
        return {"project_id": project_id, "items": activity[page.offset:page.offset + page.limit],
                "total": len(activity),
                "next_offset": page.offset + page.limit if page.offset + page.limit < len(activity) else None}

    @mcp.tool(annotations=read)
    def factory_asset_metadata(project_id: str, relative_path: str) -> dict:
        """Inspect a project render or asset: media type, size, SHA-256, optional video dimensions/duration and secure download link."""
        import hashlib
        import mimetypes
        import subprocess

        root = factory.project(project_id).resolve()
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] not in {"renders", "assets"}:
            raise ValueError("Choose a media file under renders/ or assets/")
        path = (root / relative).resolve()
        if (not path.is_relative_to(root) or not path.is_file()
                or path.suffix.lower() not in {".mp4", ".mov", ".webm", ".wav", ".mp3", ".png", ".jpg", ".jpeg"}):
            raise ValueError("Media file is unavailable")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        result = {"project_id": project_id, "path": relative.as_posix(), "filename": path.name,
                  "bytes": path.stat().st_size, "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                  "sha256": digest.hexdigest()}
        if path.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}:
            try:
                probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", str(path)],
                                       capture_output=True, text=True, timeout=10, check=True)
                data = json.loads(probe.stdout)
                video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
                result.update({"duration_seconds": float(data.get("format", {}).get("duration", 0) or 0),
                               "width": video.get("width"), "height": video.get("height"), "frame_rate": video.get("r_frame_rate")})
            except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
                result["probe_note"] = "ffprobe unavailable or could not inspect this file"
        if download_signer is not None:
            result["download_url"] = download_signer.sign(project_id, relative.as_posix())
            result["download_expires_in_seconds"] = 300
        else:
            result["download_available"] = False
        return result

    @mcp.tool(annotations=read)
    def factory_job_recovery_plan(project_id: str, job_id: str) -> dict:
        """Explain safe recovery options for a job. Never retries work or assumes an interrupted provider stopped."""
        job = factory.job(project_id, job_id)
        status = job["status"]
        uncertain = status in {"queued", "running", "cancelling", "interrupted", "failed"}
        request = job.get("request", {})
        return {"project_id": project_id, "job_id": job_id, "status": status,
                "may_have_external_side_effects": uncertain,
                "safe_to_retry_now": False, "requires_human_review_before_retry": True,
                "plan_id": request.get("plan_id"), "step_id": request.get("step", {}).get("id"),
                "guidance": ("Inspect outputs and provider status before retrying; the previous operation may still complete or bill." if uncertain
                             else "Review the project checkpoint and outputs, then submit an explicitly approved retry with a fresh idempotency key."),
                "result": job.get("result")}

    @mcp.tool(annotations=read)
    def factory_publish_handoff(project_id: str, relative_path: str, platform: str,
                                 title: str = "", caption: str = "", hashtags: list[str] | None = None) -> dict:
        """Prepare a publish-ready handoff packet and expiring video link. Does not post or upload to any platform."""
        allowed = {"instagram", "tiktok", "youtube", "youtube_shorts", "facebook", "linkedin", "x", "other"}
        platform_key = platform.strip().lower().replace(" ", "_")
        if platform_key not in allowed:
            raise ValueError(f"Choose a platform from: {', '.join(sorted(allowed))}")
        metadata = factory_asset_metadata(project_id, relative_path)
        clean_tags = [tag.strip().lstrip("#") for tag in (hashtags or []) if tag.strip()][:30]
        return {"project_id": project_id, "platform": platform_key,
                "title": title.strip()[:200], "caption": caption.strip()[:5000],
                "hashtags": clean_tags, "asset": metadata,
                "checklist": ["Review the final video and caption", "Confirm platform crop, captioning and music rights", "Publish manually in the selected platform"],
                "published": False}

    @mcp.tool(annotations=write)
    def factory_configure_project(params: ConfigureProject) -> dict:
        """Replace project defaults using optimistic revision checking. Invalidates saved plans; does not alter running jobs."""
        return factory.configure(params.project_id, params.config, params.expected_revision)

    @mcp.tool(annotations=read)
    def factory_stage_context(project_id: str, stage: str | None = None) -> dict:
        """Get stage instructions, native tool permissions and checkpoint. Defaults to the next incomplete stage."""
        return factory.stage_context(project_id, stage)

    @mcp.tool(annotations=write)
    async def factory_checkpoint(params: CheckpointInput) -> dict:
        """Validate and save canonical artifacts through existing checkpoint/gate enforcement. Never invent approval evidence."""
        result = factory.checkpoint(**params.model_dump())
        database = getattr(factory, "database", None)
        if database is None:
            return result
        from content_factory.hosted import _workspace_id
        workspace_id = _workspace_id.get()
        if not workspace_id:
            return result
        from lib.checkpoint import read_checkpoint
        checkpoint = read_checkpoint(factory.root, params.project_id, params.stage)
        if checkpoint is None:
            return {**result, "studio_progress": "checkpoint_saved_but_not_mirrored"}
        approval_needed = checkpoint.get("status") == "awaiting_human" and not checkpoint.get("human_approved", False)
        try:
            from lib.pipeline_loader import get_stage_order, load_pipeline
            pipeline_type = str(factory.marker(params.project_id).get("pipeline_type", ""))
            stage_order = get_stage_order(load_pipeline(pipeline_type))
            if approval_needed:
                project_status = "review"
            elif checkpoint.get("status") == "completed" and stage_order and params.stage == stage_order[-1]:
                project_status = "complete"
            elif params.stage == "research" and checkpoint.get("status") in {"in_progress", "awaiting_human"}:
                project_status = "research"
            else:
                project_status = "in_progress"
            await database.sync_project_progress(workspace_id, params.project_id, params.stage,
                checkpoint.get("status", params.status), approval_needed, project_status)
            return {**result, "studio_progress": "synced", "approval_needed": approval_needed}
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Studio progress mirror failed for project %s (%s)",
                params.project_id, type(exc).__name__)
            return {**result, "studio_progress": "sync_pending", "approval_needed": approval_needed}

    @mcp.tool(annotations={**read, "openWorldHint": True})
    def factory_validate_route(params: PlanInput) -> dict:
        """Validate an AI-authored route against user pins, schemas, stage permissions, availability and estimated cost limits. Executes nothing."""
        return factory.validate_plan(params.project_id, params.plan)

    @mcp.tool(annotations={**read, "openWorldHint": True})
    def factory_preflight_route(params: PlanInput) -> dict:
        """Run a no-execution production preflight for schema, plugin health, stage permissions, profile constraints and estimated cost."""
        result = factory.validate_plan(params.project_id, params.plan)
        return {"ready_to_save": True, "ready_to_submit": False, "preflight": result,
                "next_action": "Review route and estimates, then save it. Submission still requires pipeline gates and any configured approval evidence."}

    @mcp.tool(annotations=write)
    def factory_save_route(params: PlanInput) -> dict:
        """Save an immutable validated route with resolved parameters and plugin versions. Does not approve or run it."""
        return factory.save_plan(params.project_id, params.plan)

    hosted_submit = getattr(factory, "submit_hosted", None)
    if hosted_submit is not None:
        @mcp.tool(annotations={**write, "idempotentHint": True, "openWorldHint": True})
        async def factory_submit_job(params: SubmitInput) -> dict:
            """Submit a validated pipeline step to the durable workspace queue. Returns job_id; may invoke paid providers."""
            return await factory.submit_hosted(**params.model_dump())
    else:
        @mcp.tool(annotations={**write, "idempotentHint": True, "openWorldHint": True})
        def factory_submit_job(params: SubmitInput) -> dict:
            """Submit one saved route step to a durable local worker after predecessor gates. Returns job_id; may invoke paid providers."""
            return factory.submit(**params.model_dump())

    hosted_job_status = getattr(factory, "hosted_job_status", None)
    if hosted_job_status is not None:
        @mcp.tool(annotations=read)
        async def factory_job_status(project_id: str, job_id: str, log_tail_bytes: int = 0) -> dict:
            """Inspect the durable workspace job record and its bounded result."""
            if not 0 <= log_tail_bytes <= 32000:
                raise ValueError("log_tail_bytes must be between 0 and 32000")
            result = await factory.hosted_job_status(project_id, job_id, log_tail_bytes)
            return _trim_untrusted_research(result)
    else:
        @mcp.tool(annotations=read)
        def factory_job_status(project_id: str, job_id: str, log_tail_bytes: int = 0) -> dict:
            """Inspect a persisted job, configuration snapshot and result. Optional log tail is capped at 32KB."""
            if not 0 <= log_tail_bytes <= 32000:
                raise ValueError("log_tail_bytes must be between 0 and 32000")
            return _trim_untrusted_research(factory.job(project_id, job_id, log_tail_bytes))

    hosted_cancel = getattr(factory, "cancel_hosted", None)
    if hosted_cancel is not None:
        @mcp.tool(annotations={**write, "idempotentHint": True})
        async def factory_cancel_job(project_id: str, job_id: str) -> dict:
            """Cancel queued hosted work or request cancellation from its leased worker."""
            return await factory.cancel_hosted(project_id, job_id)
    else:
        @mcp.tool(annotations={**write, "idempotentHint": True})
        def factory_cancel_job(project_id: str, job_id: str) -> dict:
            """Request termination of local worker processes. Remote provider jobs may continue; cancellation does not refund charges."""
            return factory.cancel(project_id, job_id)

    @mcp.tool(annotations={**write, "idempotentHint": True})
    def factory_reconcile_job(project_id: str, job_id: str) -> dict:
        """Mark a job interrupted only if its recorded supervisor no longer exists. Never restarts uncertain or potentially paid work."""
        return factory.reconcile(project_id, job_id)

    @mcp.tool(annotations=read)
    async def factory_outputs(project_id: str, offset: int = 0, limit: int = 30) -> dict:
        """List project assets, renders and artifacts with local paths and sizes."""
        result = factory.outputs(project_id, Page(offset=offset, limit=limit))
        database = getattr(factory, "database", None)
        if database is not None:
            from content_factory.hosted import _workspace_id
            workspace_id = _workspace_id.get()
            if workspace_id:
                stored = await database.media_objects(workspace_id, project_id)
                present = {Path(item["path"]).relative_to(factory.project(project_id)).as_posix()
                           for item in result["items"] if item.get("path")}
                for item in stored:
                    if item["relative_path"] not in present:
                        result["items"].append({"path": str(factory.project(project_id) / item["relative_path"]),
                            "name": item["filename"], "bytes": item["bytes"], "storage": "supabase"})
        if download_signer:
            for item in result["items"]:
                relative = Path(item["path"]).relative_to(factory.project(project_id)).as_posix()
                try:
                    from content_factory.media import validate_relative_media_path
                    validate_relative_media_path(relative)
                    item.update(download_url=download_signer.sign(project_id, relative), expires_in_seconds=300)
                except ValueError:
                    pass
        return result

    @mcp.tool(annotations=read)
    async def factory_export_media(project_id: str, relative_path: str, mode: Literal["link", "bytes"] = "link",
                             offset: int = 0, max_bytes: int = 196608, expected_sha256: str | None = None) -> dict:
        """Export playable media via a five-minute link, or bounded base64 bytes on any transport. For chunks, pass next_offset and expected_sha256; decode and concatenate bytes locally."""
        from content_factory.media import export_media, media_path, validate_relative_media_path
        database = getattr(factory, "database", None)
        from content_factory.hosted import _workspace_id
        try:
            media_path(factory, project_id, relative_path)
        except ValueError:
            if database is None:
                raise
            workspace_id = _workspace_id.get()
            rows = await database.media_objects(workspace_id or "", project_id)
            row = next((item for item in rows if item["relative_path"] == validate_relative_media_path(relative_path)), None)
            if row is None:
                raise ValueError("Media file is unavailable")
            if mode == "bytes":
                return await database.export_media_bytes(workspace_id or "", project_id, relative_path,
                    row, offset, max_bytes, expected_sha256)
            if mode != "link":
                raise ValueError("mode must be link or bytes")
            return {"project_id": project_id, "relative_path": relative_path, "filename": row["filename"],
                "mime_type": row["mime_type"], "bytes": row["bytes"], "sha256": row["sha256"],
                "download_url": download_signer.sign(project_id, relative_path) if download_signer else None,
                "expires_in_seconds": 300, "storage": "supabase"}
        return export_media(factory, project_id, relative_path, download_signer, mode, offset, max_bytes, expected_sha256)

    if download_signer is not None:
        @mcp.tool(annotations={**read, "openWorldHint": True})
        async def factory_download_url(project_id: str, relative_path: str) -> dict:
            """Create a five-minute browser download link for one rendered media file. Treat the link as a secret until it expires."""
            try:
                path = download_signer.media_path(factory, project_id, relative_path)
                filename, size = path.name, path.stat().st_size
            except ValueError:
                from content_factory.hosted import _workspace_id
                database = getattr(factory, "database", None)
                workspace_id = _workspace_id.get()
                rows = await database.media_objects(workspace_id or "", project_id) if database else []
                from content_factory.media import validate_relative_media_path
                row = next((item for item in rows if item["relative_path"] == validate_relative_media_path(relative_path)), None)
                if row is None:
                    raise ValueError("Media file is unavailable")
                filename, size = row["filename"], row["bytes"]
            return {"url": download_signer.sign(project_id, relative_path), "filename": filename,
                    "bytes": size, "expires_in_seconds": 300}

    from content_factory.autonomous_tools import register
    register(mcp, factory, download_signer)
    return mcp


def main():
    parser = argparse.ArgumentParser(description="Content Factory MCP (local stdio transport)")
    parser.add_argument("--projects-dir", type=Path, help="Override project root; default follows OPENMONTAGE_PROJECTS_DIR")
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
        factory = Factory(projects_dir=args.projects_dir)
    build_server(factory).run(transport="stdio")


if __name__ == "__main__":
    main()
