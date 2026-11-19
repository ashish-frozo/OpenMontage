"""First-party REST API for OpenMontage Studio.

This is the Studio web application's HTTP interface. It is intentionally
separate from the open-source MCP transport; both adapters share the same
registered production operations and durable worker implementation.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

from content_factory.hosted import (
    StudioDatabase,
    StudioJobMirror,
    WorkspaceAuthorizationMiddleware,
    WorkspaceDownloadSigner,
    WorkspaceFactory,
    _WORKSPACE_UUID,
    _project_ids,
    _studio_api_actor,
    _workspace_id,
)
from content_factory.server import build_server, call_registered_tool


_SAFE_OPERATIONS = {
    "factory_artifact_schema", "factory_asset_metadata", "factory_cancel_job",
    "factory_checkpoint", "factory_compile_motion", "factory_config_schema",
    "factory_configure_project", "factory_create_project", "factory_export_media",
    "factory_find_assets", "factory_instruction", "factory_job_status", "factory_jobs",
    "factory_local_voices", "factory_motion_presets", "factory_motion_resources",
    "factory_motion_scene_schema", "factory_next_action", "factory_operation",
    "factory_operations", "factory_outputs", "factory_pipelines", "factory_plugins",
    "factory_preflight_route", "factory_preview_revision", "factory_project",
    "factory_project_activity", "factory_projects", "factory_read_project_file",
    "factory_review_scene_plan", "factory_revision_plan", "factory_routes",
    "factory_save_revision", "factory_save_route", "factory_stage_context",
    "factory_style", "factory_styles", "factory_submit_job", "factory_validate_motion_scene",
    "factory_validate_route", "factory_write_workspace_file",
}
_SAFE_OPENSHORTS_READS = {"openshorts_get_job_status", "openshorts_list_clips"}
_WRITE_ROLES = {"owner", "admin", "producer"}
_UUID_IN_TEXT = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class StudioAPIAuth:
    def __init__(self, database: StudioDatabase, supabase_url: str):
        self.database = database
        self.auth_url = supabase_url.rstrip("/") + "/auth/v1/user"

    async def identity(self, bearer: str) -> str | None:
        if not bearer or len(bearer) > 8192:
            return None
        async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3), follow_redirects=False) as client:
            response = await client.get(self.auth_url, headers={
                "apikey": self.database.api_key,
                "Authorization": f"Bearer {bearer}",
            })
        if response.status_code != 200:
            return None
        try:
            user_id = response.json().get("id")
        except (ValueError, AttributeError):
            return None
        return user_id if isinstance(user_id, str) and _UUID_IN_TEXT.fullmatch(user_id) else None

    async def membership_role(self, workspace_id: str, user_id: str) -> str | None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3), follow_redirects=False) as client:
            response = await client.get(self.database.rest + "/workspace_members", headers=self.database.headers,
                params={"select": "role", "workspace_id": f"eq.{workspace_id}",
                        "user_id": f"eq.{user_id}", "limit": "1"})
        response.raise_for_status()
        rows = response.json()
        return str(rows[0]["role"]) if isinstance(rows, list) and rows and isinstance(rows[0], dict) and rows[0].get("role") else None


def _config(config: dict) -> tuple[StudioDatabase, WorkspaceFactory, WorkspaceDownloadSigner, str]:
    required = ("supabase_url", "supabase_secret_key", "base_url", "projects_dir", "media_signing_secret")
    if any(not isinstance(config.get(key), str) or not config[key] for key in required):
        raise ValueError("Studio API configuration is incomplete")
    origin = urlsplit(config["base_url"])
    if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
            or origin.path not in {"", "/"} or origin.query or origin.fragment):
        raise ValueError("Studio API base_url must be a public HTTPS origin without path, query, or fragment")
    database = StudioDatabase(config["supabase_url"], config["supabase_secret_key"])
    factory = WorkspaceFactory(config["projects_dir"], database)
    signer = WorkspaceDownloadSigner(config["base_url"], config["media_signing_secret"])
    return database, factory, signer, config["supabase_url"]


def build_studio_api(config: dict) -> Starlette:
    database, factory, signer, supabase_url = _config(config)
    auth = StudioAPIAuth(database, supabase_url)
    operations = build_server(factory, server_class=FastMCP, download_signer=signer)
    job_runtime = WorkspaceAuthorizationMiddleware(database, operations, factory)

    async def health(_request: Request):
        return JSONResponse({"ok": True, "service": "openmontage-studio-api", "api_version": 1})

    async def call_operation(request: Request):
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 1_000_000):
            return JSONResponse({"error": "Request body is too large."}, status_code=413)
        authorization = request.headers.get("authorization", "")
        scheme, _, bearer = authorization.partition(" ")
        if scheme.lower() != "bearer" or not bearer:
            return JSONResponse({"error": "Sign in is required."}, status_code=401)
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({"error": "Expected a JSON request body."}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "Invalid request body."}, status_code=400)
        workspace_id = body.get("workspace_id")
        arguments = body.get("arguments", {})
        operation = request.path_params["operation"]
        if not isinstance(workspace_id, str) or not _WORKSPACE_UUID.fullmatch(workspace_id):
            return JSONResponse({"error": "A valid workspace is required."}, status_code=400)
        if not isinstance(arguments, dict) or len(json.dumps(arguments)) > 900_000:
            return JSONResponse({"error": "Invalid or oversized operation arguments."}, status_code=400)
        if operation not in _SAFE_OPERATIONS and operation not in _SAFE_OPENSHORTS_READS:
            return JSONResponse({"error": "This operation is not available through Studio."}, status_code=404)
        try:
            user_id = await auth.identity(bearer)
            if user_id is None:
                return JSONResponse({"error": "Your session has expired. Sign in again."}, status_code=401)
            role = await auth.membership_role(workspace_id, user_id)
            if role is None:
                return JSONResponse({"error": "Workspace access was not found."}, status_code=403)
            if operation in _SAFE_OPENSHORTS_READS:
                # Status requests are read-only but still bound to a workspace
                # project to prevent cross-workspace OpenShorts job lookups.
                native_project_id = arguments.get("project_id")
                if not isinstance(native_project_id, str) or not await database.authorize_project(workspace_id, native_project_id):
                    return JSONResponse({"error": "Project is not available in this workspace."}, status_code=404)
            else:
                tool = operations._tool_manager.get_tool(operation)
                annotations = tool.annotations or {}
                if hasattr(annotations, "model_dump"):
                    annotations = annotations.model_dump()
                if not isinstance(annotations, dict):
                    annotations = {}
                if annotations.get("readOnlyHint") is not True and role not in _WRITE_ROLES:
                    return JSONResponse({"error": "Producer permission is required for this operation."}, status_code=403)
            project_ids = set(_project_ids(arguments))
            if len(project_ids) > 1:
                return JSONResponse({"error": "An operation cannot span projects."}, status_code=400)
            if project_ids and not await database.authorize_project(workspace_id, next(iter(project_ids))):
                return JSONResponse({"error": "Project is not available in this workspace."}, status_code=404)
            workspace_token = _workspace_id.set(workspace_id)
            actor_token = _studio_api_actor.set({"sub": user_id, "member_role": role})
            try:
                job_runtime.job_runner.start()
                if operation in _SAFE_OPENSHORTS_READS:
                    adapter = factory.registry.plugins.get("openmontage")
                    native_registry = getattr(adapter, "registry", None)
                    if native_registry is None:
                        return JSONResponse({"error": "OpenShorts status is unavailable."}, status_code=503)
                    native_registry.ensure_discovered()
                    native = native_registry.get(operation)
                    if native is None:
                        return JSONResponse({"error": "OpenShorts status is unavailable."}, status_code=503)
                    import jsonschema
                    native_arguments = {key: value for key, value in arguments.items() if key != "project_id"}
                    jsonschema.validate(native_arguments, native.input_schema)
                    api_key = await database.decrypt_provider_credential(workspace_id, "openshorts")
                    result = native.execute(native_arguments, api_key=api_key)
                    result = {
                        "success": result.success, "data": result.data,
                        "error": result.error, "cost_usd": result.cost_usd,
                    }
                    if not result["success"]:
                        return JSONResponse({"error": result.get("error") or "OpenShorts request failed."}, status_code=502)
                else:
                    result = await call_registered_tool(operations, operation, arguments)
            finally:
                _studio_api_actor.reset(actor_token)
                _workspace_id.reset(workspace_token)
            return JSONResponse({"result": result})
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
        except httpx.HTTPError:
            return JSONResponse({"error": "Workspace authorization is temporarily unavailable."}, status_code=503)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Studio API operation %s failed (%s)", operation, type(exc).__name__)
            return JSONResponse({"error": "The requested Studio operation failed. Check project activity before retrying."}, status_code=422)

    async def download_media(request: Request):
        resolved = signer.resolve(request.path_params["ticket"])
        if resolved is None:
            return PlainTextResponse("Link expired or invalid", status_code=404)
        workspace_id, project_id, relative_path = resolved
        try:
            if not await database.authorize_project(workspace_id, project_id):
                return PlainTextResponse("Link expired or invalid", status_code=404)
            from content_factory.media import validate_relative_media_path
            relative_path = validate_relative_media_path(relative_path)
            token = _workspace_id.set(workspace_id)
            try:
                try:
                    path = signer.media_path(factory, project_id, relative_path)
                except ValueError:
                    path = factory.project(project_id) / relative_path
            finally:
                _workspace_id.reset(token)
        except (httpx.HTTPError, OSError, ValueError):
            return PlainTextResponse("Link expired or invalid", status_code=404)
        if not path.is_file():
            try:
                signed_url = await database.signed_media_url(workspace_id, project_id, relative_path)
            except (httpx.HTTPError, OSError, ValueError, RuntimeError):
                return PlainTextResponse("Media is unavailable", status_code=404)
            return RedirectResponse(signed_url, status_code=302, headers={"Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
        return FileResponse(path, filename=path.name, content_disposition_type="inline",
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                     "Referrer-Policy": "no-referrer"})

    @asynccontextmanager
    async def lifespan(_app):
        job_runtime.job_runner.start()
        mirror = StudioJobMirror(database, factory.base_root)
        mirror.start()
        try:
            yield
        finally:
            mirror.stop()
            await job_runtime.job_runner.stop()

    return Starlette(debug=False, routes=[
        Route("/healthz", health, methods=["GET"]),
        Route("/v1/operations/{operation}", call_operation, methods=["POST"]),
        Route("/download/{ticket}", download_media, methods=["GET"]),
    ], lifespan=lifespan)


def main():
    parser = argparse.ArgumentParser(description="OpenMontage Studio REST API and durable worker")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    if args.config.is_symlink() or not args.config.is_file():
        raise ValueError("Configuration must be a regular file")
    if stat.S_IMODE(args.config.stat().st_mode) & 0o077:
        raise ValueError("Configuration contains credentials; set permissions to 600")
    os.umask(0o077)
    config = json.loads(args.config.read_text())
    encryption_key = config.get("credential_encryption_key")
    if isinstance(encryption_key, str) and encryption_key:
        os.environ["STUDIO_CREDENTIAL_ENCRYPTION_KEY"] = encryption_key
    openshorts_url = config.get("openshorts_api_url")
    if isinstance(openshorts_url, str) and openshorts_url:
        os.environ["OPENSHORTS_API_URL"] = openshorts_url
    app = build_studio_api(config)
    uvicorn.run(app, host=config.get("host", "127.0.0.1"), port=args.port, access_log=False)


if __name__ == "__main__":
    main()
