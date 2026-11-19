"""Workspace-scoped remote MCP mode for OpenMontage Studio.

This service is separate from the owner-only GitHub OAuth deployment. Studio
issues opaque, revocable workspace tokens; every project tool call is checked
against Supabase before it can reach a workspace-specific Factory directory.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import sqlite3
import stat
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, AuthProvider
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware, MiddlewareContext
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse

from content_factory.server import build_server
from content_factory.service import Factory
from content_factory.service import _hosted_job_environment


_workspace_id: ContextVar[str | None] = ContextVar("openmontage_workspace_id", default=None)
_WORKSPACE_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_GOOGLE_PROVIDER_IDS = {"google", "google_tts", "google_imagen", "gemini", "gemini_omni", "veo"}
_LOCAL_TO_STUDIO_STATUS = {
    "queued": "queued",
    "running": "running",
    "completed": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "cancelling": "reconciling",
    "timed_out": "reconciling",
    "interrupted": "reconciling",
}


class StudioDatabase:
    def __init__(self, supabase_url: str, service_role_key: str):
        self.rest = supabase_url.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        }
        self.storage = supabase_url.rstrip("/") + "/storage/v1"

    @staticmethod
    def _media_key(workspace_id: str, project_id: str, relative_path: str) -> str:
        if not _WORKSPACE_UUID.fullmatch(workspace_id) or not _WORKSPACE_UUID.fullmatch(project_id):
            raise ValueError("Invalid media ownership")
        from content_factory.media import validate_relative_media_path
        return f"{workspace_id}/{project_id}/{validate_relative_media_path(relative_path)}"

    async def upload_media(self, workspace_id: str, project_id: str, relative_path: str, path: Path,
                           job_id: str | None = None, worker_name: str | None = None) -> dict:
        """Resumably copy one bounded project media file into the private bucket."""
        object_key = self._media_key(workspace_id, project_id, relative_path)
        size = path.stat().st_size
        if size <= 0 or size > 20 * 1024 * 1024 * 1024:
            raise ValueError("Media file is empty or exceeds the 20GB hosted limit")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        tus = self.storage + "/upload/resumable"
        metadata = {"bucketName": "studio-media", "objectName": object_key,
                    "contentType": mime, "cacheControl": "3600"}
        encoded = ",".join(f"{key} {base64.b64encode(value.encode()).decode()}" for key, value in metadata.items())
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10), follow_redirects=False) as client:
            response = await client.post(tus, headers={**self.headers, "Content-Type": "application/offset+octet-stream",
                "Tus-Resumable": "1.0.0", "Upload-Length": str(size), "Upload-Metadata": encoded, "x-upsert": "true"})
            response.raise_for_status()
            location = response.headers.get("Location")
            if not location:
                raise RuntimeError("Storage did not return a resumable upload location")
            upload_url = str(httpx.URL(tus).join(location))
            if httpx.URL(upload_url).host != httpx.URL(tus).host or httpx.URL(upload_url).scheme != "https":
                raise RuntimeError("Storage returned an unsafe upload location")
            offset = 0
            last_heartbeat = time.monotonic()
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while offset < size:
                    if job_id and worker_name and time.monotonic() - last_heartbeat >= 20:
                        if not await self.heartbeat_job(job_id, worker_name, 300):
                            raise RuntimeError("Hosted job lease was lost during media replication")
                        last_heartbeat = time.monotonic()
                    chunk = stream.read(6 * 1024 * 1024)
                    digest.update(chunk)
                    patch = await client.patch(upload_url, content=chunk, headers={"Tus-Resumable": "1.0.0",
                        "Upload-Offset": str(offset), "Content-Type": "application/offset+octet-stream"})
                    patch.raise_for_status()
                    actual = int(patch.headers.get("Upload-Offset", "-1"))
                    if actual != offset + len(chunk):
                        raise RuntimeError("Resumable media upload offset mismatch")
                    offset = actual
        record = {"workspace_id": workspace_id, "project_id": project_id, "relative_path": relative_path,
                  "object_key": object_key, "filename": path.name, "mime_type": mime, "bytes": size,
                  "sha256": digest.hexdigest()}
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            saved = await client.post(self.rest + "/studio_media_objects", headers={**self.headers,
                "Prefer": "resolution=merge-duplicates,return=minimal"}, json=record)
        saved.raise_for_status()
        return record

    async def media_objects(self, workspace_id: str, project_id: str) -> list[dict]:
        if not _WORKSPACE_UUID.fullmatch(workspace_id) or not _WORKSPACE_UUID.fullmatch(project_id):
            return []
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3)) as client:
            response = await client.get(self.rest + "/studio_media_objects", headers=self.headers,
                params={"select": "relative_path,object_key,filename,mime_type,bytes,sha256",
                        "workspace_id": f"eq.{workspace_id}", "project_id": f"eq.{project_id}",
                        "order": "relative_path.asc", "limit": "1000"})
        response.raise_for_status()
        rows = response.json()
        return rows if isinstance(rows, list) else []

    async def signed_media_url(self, workspace_id: str, project_id: str, relative_path: str) -> str:
        key = self._media_key(workspace_id, project_id, relative_path)
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3)) as client:
            response = await client.post(f"{self.storage}/object/sign/studio-media/{quote(key, safe='/')}",
                headers=self.headers, json={"expiresIn": 300})
        response.raise_for_status()
        signed = response.json().get("signedURL")
        if not isinstance(signed, str) or not signed.startswith("/") or signed.startswith("//"):
            raise RuntimeError("Storage returned an invalid signed URL")
        return self.storage + signed

    async def export_media_bytes(self, workspace_id: str, project_id: str, relative_path: str,
                                 row: dict, offset: int, max_bytes: int, expected_sha256: str | None) -> dict:
        from content_factory.media import validate_relative_media_path
        if row.get("relative_path") != validate_relative_media_path(relative_path):
            raise ValueError("Media record does not match the requested path")
        if not 0 <= offset <= row["bytes"] or not 1 <= max_bytes <= 262144:
            raise ValueError("Invalid media export range")
        if expected_sha256 and expected_sha256 != row["sha256"]:
            raise ValueError("Media changed; restart export from offset zero")
        key = self._media_key(workspace_id, project_id, relative_path)
        end = min(offset + max_bytes, row["bytes"]) - 1
        headers = {**self.headers, "Range": f"bytes={offset}-{end}"}
        chunk_parts = []
        received = 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5)) as client:
            async with client.stream("GET", f"{self.storage}/object/authenticated/studio-media/{quote(key, safe='/')}", headers=headers) as response:
                if response.status_code not in {200, 206}:
                    response.raise_for_status()
                    raise RuntimeError("Storage did not return the requested media range")
                if response.status_code == 200 and row["bytes"] - offset > max_bytes:
                    raise RuntimeError("Storage did not honor the bounded media range")
                async for part in response.aiter_bytes():
                    received += len(part)
                    if received > max_bytes:
                        raise RuntimeError("Storage returned more than the requested media range")
                    chunk_parts.append(part)
        chunk = b"".join(chunk_parts)
        if len(chunk) > max_bytes or (offset + len(chunk) < row["bytes"] and len(chunk) != max_bytes):
            raise RuntimeError("Storage returned an invalid media range")
        end_offset = offset + len(chunk)
        return {"project_id": project_id, "relative_path": relative_path, "filename": row["filename"],
            "mime_type": row["mime_type"], "bytes": row["bytes"], "sha256": row["sha256"],
            "encoding": "base64", "data": base64.b64encode(chunk).decode(), "offset": offset,
            "returned_bytes": len(chunk), "next_offset": end_offset if end_offset < row["bytes"] else None}

    async def rpc(self, function: str, payload: dict) -> object:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            response = await client.post(f"{self.rest}/rpc/{function}", headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()

    async def authorize_project(self, workspace_id: str, project_id: str) -> bool:
        if not _WORKSPACE_UUID.fullmatch(workspace_id) or not _WORKSPACE_UUID.fullmatch(project_id):
            return False
        result = await self.rpc("authorize_workspace_project", {
            "target_workspace_id": workspace_id,
            "target_project_id": project_id,
        })
        return result is True

    async def sync_project_progress(self, workspace_id: str, project_id: str, stage: str,
                                    checkpoint_status: str, approval_needed: bool,
                                    project_status: str) -> bool:
        if not _WORKSPACE_UUID.fullmatch(workspace_id) or not _WORKSPACE_UUID.fullmatch(project_id):
            raise ValueError("Invalid project progress identity")
        result = await self.rpc("sync_studio_project_progress", {
            "target_workspace_id": workspace_id,
            "target_project_id": project_id,
            "target_stage": stage,
            "target_checkpoint_status": checkpoint_status,
            "target_approval_needed": approval_needed,
            "target_project_status": project_status,
        })
        if result is not True:
            raise RuntimeError("Studio did not accept the project progress update")
        return True

    async def sync_job_statuses(self, workspace_id: str, records: list[dict]) -> int:
        if not _WORKSPACE_UUID.fullmatch(workspace_id) or not records or len(records) > 500:
            raise ValueError("Invalid job mirror batch")
        result = await self.rpc("sync_hosted_job_statuses", {
            "target_workspace_id": workspace_id,
            "job_records": records,
        })
        if not isinstance(result, int) or result != len(records):
            raise RuntimeError("Studio did not accept the complete job mirror batch")
        return result

    async def enqueue_job(self, workspace_id: str, project_id: str, operation: str, key: str,
                          created_by: str, inputs: dict, estimate: float, provider: str | None) -> dict:
        rows = await self.rpc("enqueue_studio_job", {
            "target_workspace_id": workspace_id,
            "target_project_id": project_id,
            "target_operation": operation,
            "target_idempotency_key": key,
            "target_created_by": created_by,
            "target_input": inputs,
            "target_estimated_cost": estimate,
            "target_provider": provider,
        })
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise RuntimeError("Supabase did not return the durable job record")
        row = rows[0]
        if not row.get("id") or row.get("status") not in {"queued", "running", "cancelling", "succeeded", "failed", "cancelled", "reconciling"}:
            raise RuntimeError("Supabase returned an invalid job record")
        row["deduplicated"] = row.get("idempotency_key") != key
        return row

    async def claim_job(self, worker_name: str, lease_seconds: int = 300) -> dict | None:
        rows = await self.rpc("claim_studio_job", {"worker_name": worker_name, "lease_seconds": lease_seconds})
        if not isinstance(rows, list):
            raise RuntimeError("Supabase returned an invalid claim response")
        return rows[0] if rows and isinstance(rows[0], dict) else None

    async def heartbeat_job(self, job_id: str, worker_name: str, lease_seconds: int = 300) -> bool:
        result = await self.rpc("heartbeat_studio_job", {
            "target_job_id": job_id, "worker_name": worker_name, "lease_seconds": lease_seconds,
        })
        return result is True

    async def report_job_progress(self, job_id: str, worker_name: str, progress: int, label: str = "") -> bool:
        result = await self.rpc("report_studio_job_progress", {
            "target_job_id": job_id, "worker_name": worker_name,
            "progress_value": progress, "stage_label": label[:160],
        })
        return result is True

    async def finish_job(self, job_id: str, worker_name: str, succeeded: bool, result: dict | None, error: dict | None) -> bool:
        response = await self.rpc("finish_studio_job", {
            "target_job_id": job_id, "worker_name": worker_name, "succeeded": succeeded,
            "job_result": result, "job_error": error,
        })
        return response is True

    async def reconcile_job(self, job_id: str, worker_name: str, reason: str) -> bool:
        result = await self.rpc("reconcile_studio_job", {
            "target_job_id": job_id, "worker_name": worker_name, "reason": reason[:160],
        })
        return result is True

    async def cancel_job(self, workspace_id: str, project_id: str, job_id: str) -> dict:
        result = await self.rpc("cancel_studio_job", {
            "target_workspace_id": workspace_id,
            "target_project_id": project_id,
            "target_job_id": job_id,
        })
        if not isinstance(result, dict) or not result.get("id"):
            raise RuntimeError("Supabase did not return the cancelled job record")
        return result

    async def reconcile_expired_jobs(self) -> int:
        result = await self.rpc("reconcile_expired_studio_jobs", {})
        return result if isinstance(result, int) else 0

    async def get_job(self, workspace_id: str, project_id: str, job_id: str) -> dict | None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            response = await client.get(f"{self.rest}/jobs", headers=self.headers, params={
                "select": "id,workspace_id,project_id,operation,status,progress,progress_label,input,result,error,created_at,updated_at",
                "id": f"eq.{job_id}", "workspace_id": f"eq.{workspace_id}",
                "project_id": f"eq.{project_id}", "limit": "1",
            })
        response.raise_for_status()
        rows = response.json()
        return rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None

    async def list_jobs(self, workspace_id: str, project_id: str, status: str | None, offset: int, limit: int) -> dict:
        from content_factory.models import Page
        page = Page(offset=offset, limit=limit)
        status_map = {"completed": "succeeded", "interrupted": "reconciling", "timed_out": "reconciling"}
        db_status = status_map.get(status, status)
        params: dict[str, str] = {
            "select": "id,status,operation,progress,progress_label,created_at,updated_at",
            "workspace_id": f"eq.{workspace_id}", "project_id": f"eq.{project_id}",
            "order": "created_at.desc", "offset": str(page.offset), "limit": str(page.limit),
        }
        if db_status:
            params["status"] = f"eq.{db_status}"
        headers = {**self.headers, "Prefer": "count=exact"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            response = await client.get(f"{self.rest}/jobs", headers=headers, params=params)
        response.raise_for_status()
        rows = response.json()
        content_range = response.headers.get("content-range", "*/0")
        try:
            total = int(content_range.split("/")[-1])
        except ValueError:
            total = len(rows) if isinstance(rows, list) else 0
        status_reverse = {"succeeded": "completed", "reconciling": "interrupted"}
        items = [{"job_id": str(row["id"]).replace("-", ""),
                  "status": status_reverse.get(row.get("status"), row.get("status")),
                  "operation": row.get("operation", ""),
                  "progress": row.get("progress", 0),
                  "progress_label": row.get("progress_label", "")}
                 for row in rows if isinstance(row, dict)]
        return {"items": items, "total": total,
                "next_offset": page.offset + page.limit if page.offset + page.limit < total else None}

    async def provider_credential(self, workspace_id: str, provider: str) -> tuple[bytes, str] | None:
        """Fetch one active encrypted credential; never return it to MCP clients."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            response = await client.get(f"{self.rest}/provider_connections", headers=self.headers, params={
                "select": "id", "workspace_id": f"eq.{workspace_id}", "provider": f"eq.{provider}",
                "status": "eq.connected", "limit": "2",
            })
            response.raise_for_status()
            connections = response.json()
            if not connections and provider in _GOOGLE_PROVIDER_IDS and provider != "google":
                response = await client.get(f"{self.rest}/provider_connections", headers=self.headers, params={
                    "select": "id", "workspace_id": f"eq.{workspace_id}", "provider": "eq.google",
                    "status": "eq.connected", "limit": "2",
                })
                response.raise_for_status()
                connections = response.json()
            if not isinstance(connections, list) or not connections:
                return None
            if len(connections) != 1:
                raise ValueError(f"Choose one active {provider} credential in Studio before submitting this job")
            response = await client.get(f"{self.rest}/provider_secrets", headers=self.headers, params={
                "select": "ciphertext,key_version", "workspace_id": f"eq.{workspace_id}",
                "connection_id": f"eq.{connections[0]['id']}", "limit": "1",
            })
            response.raise_for_status()
            secrets = response.json()
        if not isinstance(secrets, list) or len(secrets) != 1:
            return None
        encoded = secrets[0].get("ciphertext")
        if not isinstance(encoded, str) or not encoded.startswith("\\x"):
            raise ValueError("Stored provider credential has an invalid encoding")
        return bytes.fromhex(encoded[2:]), str(secrets[0].get("key_version", ""))

    async def decrypt_provider_credential(self, workspace_id: str, provider: str) -> str | None:
        record = await self.provider_credential(workspace_id, provider)
        if record is None:
            return None
        ciphertext, version = record
        if version != "aes-256-gcm-v1":
            raise ValueError("Stored provider credential uses an unsupported encryption version")
        encoded_key = os.environ.get("STUDIO_CREDENTIAL_ENCRYPTION_KEY", "")
        try:
            key = base64.b64decode(encoded_key, validate=True)
            if len(key) != 32 or base64.b64encode(key).decode() != encoded_key:
                raise ValueError
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            if len(ciphertext) <= 28:
                raise ValueError
            plaintext = AESGCM(key).decrypt(ciphertext[:12], ciphertext[28:] + ciphertext[12:28], None)
            return plaintext.decode("utf-8")
        except Exception as exc:
            raise ValueError("Provider credential could not be decrypted; check the Studio encryption key configuration") from exc

    async def workspace_projects(self, workspace_id: str) -> list[dict]:
        if not _WORKSPACE_UUID.fullmatch(workspace_id):
            raise ValueError("Invalid workspace")
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            response = await client.get(f"{self.rest}/projects", headers=self.headers, params={
                "select": "id,title,platform,format,status,brief,created_at,updated_at",
                "workspace_id": f"eq.{workspace_id}",
                "status": "neq.archived",
                "order": "updated_at.desc",
                "limit": "50",
            })
        response.raise_for_status()
        rows = response.json()
        return rows if isinstance(rows, list) else []

    async def workspace_project(self, workspace_id: str, project_id: str) -> dict | None:
        if not await self.authorize_project(workspace_id, project_id):
            return None
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            response = await client.get(f"{self.rest}/projects", headers=self.headers, params={
                "select": "id,title,platform,format,status,brief,created_at,updated_at",
                "workspace_id": f"eq.{workspace_id}",
                "id": f"eq.{project_id}",
                "limit": "1",
            })
        response.raise_for_status()
        rows = response.json()
        return rows[0] if isinstance(rows, list) and rows else None


class WorkspaceTokenVerifier(AuthProvider):
    """Resolve only random Studio-issued tokens by hash; never persist bearer values."""

    def __init__(self, database: StudioDatabase, base_url: str):
        super().__init__(base_url=base_url, required_scopes=["mcp:read"])
        self.database = database

    async def verify_token(self, token: str) -> AccessToken | None:
        if len(token) > 160 or not token.startswith("om_live_"):
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        try:
            rows = await self.database.rpc("resolve_workspace_mcp_token", {"presented_hash": f"\\x{token_hash}"})
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            return None
        row = rows[0]
        workspace_id = str(row.get("workspace_id", ""))
        subject_id = str(row.get("subject_id", ""))
        scopes = row.get("scopes")
        if not _WORKSPACE_UUID.fullmatch(workspace_id) or not subject_id or not isinstance(scopes, list):
            return None
        return AccessToken(
            token=token,
            client_id="openmontage-studio-workspace-token",
            scopes=[str(scope) for scope in scopes],
            subject=subject_id,
            claims={
                "sub": subject_id,
                "workspace_id": workspace_id,
                "workspace_token_id": str(row.get("token_id", "")),
                "scopes": scopes,
                "member_role": str(row.get("member_role", "")),
                "auth_method": "workspace_token",
            },
        )


class WorkspaceFactory:
    """Dispatch Factory calls to a private, durable directory per workspace."""

    def __init__(self, projects_dir: str | Path, database: StudioDatabase | None = None):
        configured_root = Path(projects_dir).expanduser()
        if configured_root.is_symlink():
            raise ValueError("Hosted projects root cannot be a symlink")
        self.base_root = configured_root.resolve()
        self.base_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.base_root, 0o700)
        self.registry = Factory().registry
        self.database = database

    def _factory(self) -> Factory:
        workspace_id = _workspace_id.get()
        if workspace_id is None or not _WORKSPACE_UUID.fullmatch(workspace_id):
            raise PermissionError("A verified Studio workspace token is required")
        root = self.base_root / workspace_id
        if root.is_symlink():
            raise PermissionError("Workspace storage path cannot be a symlink")
        root.mkdir(mode=0o700, exist_ok=True)
        os.chmod(root, 0o700)
        if root.parent != self.base_root:
            raise PermissionError("Workspace storage escaped its root")
        return Factory(registry=self.registry, projects_dir=root)

    def __getattr__(self, name: str):
        if name == "registry":
            return self.registry
        return getattr(self._factory(), name)

    async def submit_hosted(self, project_id: str, plan_id: str, step_id: str,
                            idempotency_key: str, approval_evidence: str | None = None) -> dict:
        if self.database is None:
            raise RuntimeError("Supabase-backed hosted job queue is not configured")
        workspace_id = _workspace_id.get()
        access = get_access_token()
        claims = access.claims if access else {}
        actor_id = str(claims.get("sub", ""))
        if not workspace_id or not _WORKSPACE_UUID.fullmatch(workspace_id) or not _WORKSPACE_UUID.fullmatch(actor_id):
            raise PermissionError("A verified workspace producer token is required to submit work")
        if claims.get("member_role") not in {"owner", "admin", "producer"}:
            raise PermissionError("Workspace producer permission is required to submit work")
        local_factory = self._factory()
        prepared = await asyncio.to_thread(
            local_factory.validate_submission, project_id, plan_id, step_id, idempotency_key, approval_evidence,
        )
        if "existing_job" in prepared:
            return prepared["existing_job"]
        queue_input = {
            "plan_id": plan_id,
            "step_id": step_id,
            "fingerprint": prepared["fingerprint"],
            "approval_evidence": prepared["approval_evidence"],
            "estimated_cost_usd": prepared["estimated_cost_usd"],
            "provider": prepared["provider"],
            "max_concurrent_jobs": prepared["max_concurrent_jobs"],
            "max_project_estimate_usd": prepared["max_project_estimate_usd"],
            "timeout_seconds": prepared["timeout_seconds"],
            "depends_on": prepared["depends_on"],
            "stage": prepared["step"].get("stage", ""),
        }
        row = await self.database.enqueue_job(
            workspace_id, project_id, prepared["operation"], idempotency_key,
            actor_id, queue_input, prepared["estimated_cost_usd"], prepared["provider"],
        )
        job_id = str(uuid.UUID(str(row["id"]))).replace("-", "")
        return {"job_id": job_id, "status": row["status"],
                "estimated_cost_usd": prepared["estimated_cost_usd"],
                **({"deduplicated": True} if row.get("deduplicated") else {})}

    async def hosted_jobs(self, project_id: str, status: str | None, offset: int, limit: int) -> dict:
        if self.database is None:
            raise RuntimeError("Supabase-backed hosted job queue is not configured")
        workspace_id = _workspace_id.get()
        if not workspace_id:
            raise PermissionError("A verified workspace token is required")
        if status is not None and status not in {"queued", "running", "cancelling", "waiting_approval", "completed", "succeeded", "failed", "cancelled", "interrupted", "reconciling"}:
            raise ValueError("Unknown job status")
        return await self.database.list_jobs(workspace_id, project_id, status, offset, limit)

    async def hosted_job_status(self, project_id: str, job_id: str, log_tail_bytes: int = 0) -> dict:
        if self.database is None:
            raise RuntimeError("Supabase-backed hosted job queue is not configured")
        workspace_id = _workspace_id.get()
        if not workspace_id:
            raise PermissionError("A verified workspace token is required")
        identifier(job_id)
        canonical_job_id = str(uuid.UUID(hex=job_id))
        row = await self.database.get_job(workspace_id, project_id, canonical_job_id)
        if row is None:
            # Backward compatibility for jobs created before the durable queue migration.
            return await asyncio.to_thread(self._factory().job, project_id, job_id, log_tail_bytes)
        state_map = {"succeeded": "completed", "reconciling": "interrupted"}
        queue_input = row.get("input") if isinstance(row.get("input"), dict) else {}
        result = row.get("result") if isinstance(row.get("result"), dict) else None
        if result and result.get("result_truncated"):
            try:
                local = await asyncio.to_thread(self._factory().job, project_id, job_id, log_tail_bytes)
                result = local.get("result") or result
            except Exception:
                pass
        return {
            "job_id": job_id,
            "status": state_map.get(str(row.get("status")), row.get("status")),
            "request": {"project_id": project_id, "plan_id": queue_input.get("plan_id"),
                        "step": {"id": queue_input.get("step_id"), "stage": queue_input.get("stage"),
                                 "operation": row.get("operation"), "depends_on": queue_input.get("depends_on", [])}},
            "result": result,
            "error": row.get("error"),
            "progress": row.get("progress", 0),
            "progress_label": row.get("progress_label", ""),
        }

    async def cancel_hosted(self, project_id: str, job_id: str) -> dict:
        if self.database is None:
            raise RuntimeError("Supabase-backed hosted job queue is not configured")
        workspace_id = _workspace_id.get()
        if not workspace_id:
            raise PermissionError("A verified workspace token is required")
        canonical_job_id = str(uuid.UUID(hex=identifier(job_id)))
        row = await self.database.cancel_job(workspace_id, project_id, canonical_job_id)
        return {"job_id": job_id, "status": row.get("status"), "error": row.get("error")}


class StudioJobRunner:
    """Claims durable Supabase jobs and executes each once through the existing local runner."""

    def __init__(self, database: StudioDatabase, factory: WorkspaceFactory, credential_loader):
        self.database = database
        self.factory = factory
        self.credential_loader = credential_loader
        host = getattr(os, "uname", lambda: type("Host", (), {"nodename": "worker"})())().nodename[:48]
        self.worker_name = f"openmontage-{host}-{uuid.uuid4().hex[:16]}"
        try:
            self.concurrency = max(1, min(32, int(os.environ.get("STUDIO_WORKER_CONCURRENCY", "2"))))
        except ValueError:
            self.concurrency = 2
        self._task: asyncio.Task | None = None
        self._last_reconcile = 0.0

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="studio-durable-job-runner")

    async def stop(self):
        """Stop claiming work and leave any in-flight outcome for reconciliation."""
        task = self._task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run(self):
        await asyncio.gather(*(self._run_worker(index) for index in range(self.concurrency)))

    async def _run_worker(self, index: int):
        logger = logging.getLogger(__name__)
        worker_name = f"{self.worker_name}-{index + 1}"
        while True:
            try:
                now = time.monotonic()
                if now - self._last_reconcile > 60:
                    await self.database.reconcile_expired_jobs()
                    self._last_reconcile = now
                job = await self.database.claim_job(worker_name, 300)
                if job:
                    await self._execute(job, worker_name)
                else:
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Hosted job queue pass failed (%s)", type(exc).__name__)
                await asyncio.sleep(3)

    async def _execute(self, job: dict, worker_name: str):
        logger = logging.getLogger(__name__)
        workspace_id = str(job.get("workspace_id", ""))
        project_id = str(job.get("project_id", ""))
        job_uuid = str(uuid.UUID(str(job.get("id"))))
        local_job_id = job_uuid.replace("-", "")
        queue_input = job.get("input") if isinstance(job.get("input"), dict) else {}
        context_token = _workspace_id.set(workspace_id)
        hosted_env_token = None
        local_factory = None
        try:
            if not _WORKSPACE_UUID.fullmatch(workspace_id) or not _WORKSPACE_UUID.fullmatch(project_id):
                raise ValueError("Durable job has invalid workspace or project identity")
            if not await self.database.authorize_project(workspace_id, project_id):
                raise PermissionError("Project is no longer available in this workspace")
            before_submit = await self.database.get_job(workspace_id, project_id, job_uuid)
            if before_submit and before_submit.get("status") in {"cancelling", "cancelled"}:
                await self.database.finish_job(job_uuid, worker_name, False, None, {"message": "Cancelled before execution began"})
                return
            params = {key: queue_input.get(key) for key in ("plan_id", "step_id", "approval_evidence")}
            hosted_env_token = await self.credential_loader(workspace_id, {"params": {**params, "project_id": project_id}})
            local_factory = self.factory._factory()
            local_result = await asyncio.to_thread(
                local_factory.submit, project_id, str(queue_input["plan_id"]), str(queue_input["step_id"]),
                str(job.get("idempotency_key")), queue_input.get("approval_evidence"), job_id=local_job_id,
            )
            if local_result.get("job_id") != local_job_id:
                local_job_id = str(local_result.get("job_id", local_job_id))
            last_heartbeat = time.monotonic()
            cancellation_requested = False
            while True:
                status_row = await self.database.get_job(workspace_id, project_id, job_uuid)
                if status_row and status_row.get("status") == "cancelling" and not cancellation_requested:
                    cancellation_requested = True
                    try:
                        await asyncio.to_thread(local_factory.cancel, project_id, local_job_id)
                    except Exception:
                        pass
                local_status = await asyncio.to_thread(local_factory.job, project_id, local_job_id)
                local_state = str(local_status.get("status", ""))
                if local_state in {"completed", "failed", "cancelled", "timed_out", "interrupted"}:
                    if local_state in {"timed_out", "interrupted"}:
                        await self.database.reconcile_job(job_uuid, worker_name, local_state)
                        return
                    result = local_status.get("result") if isinstance(local_status.get("result"), dict) else None
                    succeeded = local_state == "completed" and isinstance(result, dict) and result.get("success") is True
                    safe_result = self._bounded_result(result, local_job_id)
                    if succeeded:
                        try:
                            media_root = local_factory.project(project_id).resolve()
                            from content_factory.media import EXTENSIONS, validate_relative_media_path
                            synced = []
                            for folder in (media_root / "renders", media_root / "assets"):
                                if not folder.is_dir():
                                    continue
                                for path in folder.rglob("*"):
                                    if (path.is_file() and path.resolve().is_relative_to(media_root)
                                            and path.suffix.lower() in EXTENSIONS):
                                        relative = path.relative_to(media_root).as_posix()
                                        validate_relative_media_path(relative)
                                        if not await self.database.heartbeat_job(job_uuid, worker_name, 300):
                                            raise RuntimeError("Hosted job lease was lost during media replication")
                                        synced.append(await self.database.upload_media(workspace_id, project_id, relative, path,
                                                                                       job_uuid, worker_name))
                            if isinstance(safe_result, dict):
                                safe_result["media_storage"] = {"status": "ready", "objects": len(synced)}
                        except Exception as media_exc:
                            logger.warning("Media replication failed for hosted job %s (%s)", local_job_id, type(media_exc).__name__)
                            if isinstance(safe_result, dict):
                                safe_result["media_storage"] = {"status": "pending_retry", "message": "The render completed, but durable media replication is pending."}
                    error = None if succeeded else {"message": self._safe_error(result or {"status": local_state})}
                    await self.database.finish_job(job_uuid, worker_name, succeeded, safe_result, error)
                    return
                if time.monotonic() - last_heartbeat >= 25:
                    if not await self.database.heartbeat_job(job_uuid, worker_name, 300):
                        latest = await self.database.get_job(workspace_id, project_id, job_uuid)
                        if latest and latest.get("status") == "cancelling":
                            cancellation_requested = True
                            try:
                                await asyncio.to_thread(local_factory.cancel, project_id, local_job_id)
                            except Exception:
                                pass
                        elif latest and latest.get("status") == "reconciling":
                            logger.warning("Job %s lease expired; local outcome requires reconciliation", local_job_id)
                            return
                    last_heartbeat = time.monotonic()
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            # On process shutdown the local provider operation may still be in
            # flight. Record uncertainty immediately so a replacement worker
            # never repeats potentially billable work after the lease expires.
            try:
                await asyncio.shield(self.database.reconcile_job(job_uuid, worker_name, "server_shutdown"))
            except Exception:
                pass
            raise
        except Exception as exc:
            logger.warning("Hosted job %s failed before completion (%s)", local_job_id, type(exc).__name__)
            try:
                message = self._safe_error({"message": str(exc)})
                await self.database.finish_job(job_uuid, worker_name, False, None, {"message": message})
            except Exception:
                logger.warning("Could not persist terminal state for hosted job %s", local_job_id)
        finally:
            if hosted_env_token is not None:
                _hosted_job_environment.reset(hosted_env_token)
            _workspace_id.reset(context_token)

    @staticmethod
    def _bounded_result(result: dict | None, local_job_id: str) -> dict | None:
        if result is None:
            return None
        encoded = json.dumps(result, default=str, separators=(",", ":"))
        if len(encoded.encode("utf-8")) <= 1_500_000:
            return result
        return {"success": result.get("success") is True, "cost_usd": result.get("cost_usd"),
                "local_job_id": local_job_id, "result_truncated": True,
                "note": "Full result remains in the persistent hosted project volume."}

    @staticmethod
    def _safe_error(value: dict) -> str:
        message = str(value.get("message") or value.get("error") or value.get("status") or "Job failed")
        message = re.sub(r"(?i)(api[_ -]?key|token|secret|password|authorization)([\"'=:\s]+)[^,\s\"']+", r"\1\2[redacted]", message)
        return message[:1000]


class StudioJobMirror:
    """Periodically mirror lifecycle metadata; the local queue remains authoritative."""

    def __init__(self, database: StudioDatabase, projects_dir: str | Path):
        self.database = database
        self.projects_dir = Path(projects_dir).resolve()
        self._task: asyncio.Task | None = None
        self._mtimes: dict[str, int] = {}
        self._last_error: dict[str, float] = {}

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="studio-local-job-mirror")

    async def _run(self):
        while True:
            try:
                await self.sync_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.getLogger(__name__).warning("Studio job mirror pass failed (%s)", type(exc).__name__)
            await asyncio.sleep(5)

    @staticmethod
    def _read_project_jobs(database_path: Path, project_id: str) -> list[dict]:
        uri = f"file:{database_path.as_posix()}?mode=ro"
        records = []
        with sqlite3.connect(uri, uri=True, timeout=2) as db:
            rows = db.execute("SELECT id,status,data FROM jobs ORDER BY rowid").fetchall()
        for job_id, local_status, raw_data in rows:
            status = _LOCAL_TO_STUDIO_STATUS.get(local_status)
            if status is None:
                continue
            try:
                job_uuid = str(uuid.UUID(job_id))
                data = json.loads(raw_data)
                step = data.get("step") or {}
                operation = str(step.get("operation") or "")
                if not operation:
                    continue
                stage = str(step.get("stage") or "Production")
                label = f"{stage} · {operation}"[:160]
                records.append({
                    "job_id": job_uuid,
                    "project_id": project_id,
                    "operation": operation,
                    "status": status,
                    "progress": 100 if status == "succeeded" else 0,
                    "progress_label": label,
                })
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        return records

    async def sync_once(self):
        if not self.projects_dir.is_dir():
            return
        for workspace_root in self.projects_dir.iterdir():
            workspace_id = workspace_root.name
            if (workspace_root.is_symlink() or not workspace_root.is_dir()
                    or not _WORKSPACE_UUID.fullmatch(workspace_id)):
                continue
            changed: list[tuple[str, Path, int, list[dict]]] = []
            for project_root in workspace_root.iterdir():
                if project_root.is_symlink() or not project_root.is_dir():
                    continue
                try:
                    project_id = str(uuid.UUID(project_root.name))
                except ValueError:
                    continue
                database_path = project_root / "factory.sqlite3"
                if database_path.is_symlink() or not database_path.is_file():
                    continue
                cache_key = f"{workspace_id}/{project_id}"
                try:
                    mtime = database_path.stat().st_mtime_ns
                    if self._mtimes.get(cache_key) == mtime:
                        continue
                    records = await asyncio.to_thread(self._read_project_jobs, database_path, project_id)
                except (OSError, sqlite3.Error):
                    continue
                changed.append((cache_key, database_path, mtime, records))

            for cache_key, _database_path, mtime, records in changed:
                try:
                    for offset in range(0, len(records), 500):
                        await self.database.sync_job_statuses(workspace_id, records[offset:offset + 500])
                    self._mtimes[cache_key] = mtime
                except (httpx.HTTPError, ValueError, RuntimeError):
                    now = time.monotonic()
                    if now - self._last_error.get(workspace_id, 0) > 60:
                        logging.getLogger(__name__).warning("Studio job mirror unavailable for workspace %s", workspace_id)
                        self._last_error[workspace_id] = now


class WorkspaceDownloadSigner:
    """Issue five-minute bearer links bound to both a workspace and project."""

    def __init__(self, origin: str, secret: str):
        if len(secret) < 32:
            raise ValueError("Media signing secret must contain at least 32 characters")
        self.origin = origin.rstrip("/")
        self.key = hmac.new(secret.encode(), b"openmontage-workspace-media-v1", hashlib.sha256).digest()

    def media_path(self, factory: WorkspaceFactory, project_id: str, relative_path: str):
        from content_factory.media import media_path
        return media_path(factory, project_id, relative_path)

    def sign(self, project_id: str, relative_path: str, ttl_seconds: int = 300) -> str:
        workspace_id = _workspace_id.get()
        if not workspace_id or not _WORKSPACE_UUID.fullmatch(workspace_id):
            raise PermissionError("A verified Studio workspace token is required to sign media")
        payload = json.dumps({
            "w": workspace_id,
            "p": project_id,
            "f": relative_path,
            "exp": int(time.time()) + min(300, max(1, ttl_seconds)),
        }, separators=(",", ":")).encode()
        signature = hmac.new(self.key, payload, hashlib.sha256).digest()
        ticket = base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")
        return f"{self.origin}/download/{ticket}"

    def resolve(self, ticket: str) -> tuple[str, str, str] | None:
        try:
            if len(ticket) > 2048:
                return None
            raw = base64.b64decode(ticket + "=" * (-len(ticket) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(raw).decode().rstrip("=") != ticket or len(raw) <= 32:
                return None
            payload, signature = raw[:-32], raw[-32:]
            expected = hmac.new(self.key, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(expected, signature):
                return None
            data = json.loads(payload)
            workspace_id, project_id, relative_path = data["w"], data["p"], data["f"]
            if not _WORKSPACE_UUID.fullmatch(workspace_id) or not _WORKSPACE_UUID.fullmatch(project_id):
                return None
            if not isinstance(relative_path, str) or int(data["exp"]) < time.time():
                return None
            return workspace_id, project_id, relative_path
        except (ValueError, KeyError, TypeError, OSError):
            return None


def _project_ids(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "project_id" and isinstance(item, str):
                yield item
            else:
                yield from _project_ids(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _project_ids(item)


class WorkspaceAuthorizationMiddleware(Middleware):
    """Bind each tool request to its token workspace and verify project ownership."""

    def __init__(self, database: StudioDatabase, server: FastMCP, factory: WorkspaceFactory):
        self.database = database
        self.server = server
        self.workspace_factory = factory
        self._tool_read_only: dict[str, bool] | None = None
        self.job_runner = StudioJobRunner(database, factory, self._submission_environment)

    async def _read_only_tools(self) -> dict[str, bool]:
        if self._tool_read_only is None:
            tools = await self.server.list_tools()
            self._tool_read_only = {
                tool.name: bool((tool.annotations or {}).get("readOnlyHint") is True)
                for tool in tools
            }
        return self._tool_read_only

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        access = get_access_token()
        claims = access.claims if access else {}
        workspace_id = str(claims.get("workspace_id", ""))
        if not _WORKSPACE_UUID.fullmatch(workspace_id):
            raise PermissionError("This MCP token is not scoped to a workspace")
        tool_name = getattr(context.message, "name", "")
        read_only = (await self._read_only_tools()).get(tool_name, False)
        scopes = set(access.scopes if access else ())
        if not read_only and "mcp:write" not in scopes:
            raise PermissionError("This MCP token has read-only access; create a token with production access to change workspace data")
        arguments = getattr(context.message, "arguments", None) or {}
        project_ids = set(_project_ids(arguments))
        if len(project_ids) > 1:
            raise PermissionError("A tool request cannot span projects")
        if project_ids:
            try:
                allowed = await self.database.authorize_project(workspace_id, next(iter(project_ids)))
            except httpx.HTTPError as exc:
                raise PermissionError("Workspace authorization service is unavailable") from exc
            if not allowed:
                raise PermissionError("Project is not available in this workspace")
        context_token = _workspace_id.set(workspace_id)
        try:
            self.job_runner.start()
            return await call_next(context)
        finally:
            _workspace_id.reset(context_token)

    async def _submission_environment(self, workspace_id: str, arguments: dict):
        params = arguments.get("params", arguments)
        if not isinstance(params, dict):
            return None
        project_id, plan_id, step_id = (params.get(key) for key in ("project_id", "plan_id", "step_id"))
        if not all(isinstance(value, str) for value in (project_id, plan_id, step_id)):
            raise ValueError("Hosted job submission is missing its saved route identifiers")
        # Resolve the saved step using the same per-workspace Factory as the MCP operation.
        workspace_factory = getattr(self, "workspace_factory", None)
        if workspace_factory is None:
            raise RuntimeError("Hosted job credential dispatch is not configured")
        local_factory = workspace_factory._factory()
        with local_factory.db(project_id) as db:
            row = db.execute("SELECT data FROM plans WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            return None
        plan = json.loads(row["data"])
        step = next((item for item in plan.get("steps", []) if item.get("id") == step_id), None)
        if not step:
            return None
        _plugin, operation = local_factory.registry.resolve(step["operation"])
        adapter = local_factory.registry.plugins.get("openmontage")
        native_registry = getattr(adapter, "registry", None)
        if native_registry is not None:
            native_registry.ensure_discovered()
        native = native_registry.get(operation.native_tool) if native_registry and operation.native_tool else None
        if native is None:
            return _hosted_job_environment.set(({}, self._managed_environment_names(native_registry)))

        managed_names = self._managed_environment_names(native_registry)
        credentials: dict[str, str] = {}
        provider_requirements: dict[str, list[set[str]]] = {}
        selected_provider = str(params.get("preferred_provider") or "auto").strip().lower()
        selected_tool = str(params.get("preferred_tool") or "").strip()
        raw_allowed_providers = params.get("allowed_providers", [])
        if not isinstance(raw_allowed_providers, list):
            raw_allowed_providers = []
        allowed_providers = {str(value).strip().lower() for value in raw_allowed_providers if isinstance(value, str)}
        is_selector = native.provider == "selector" or native.name.endswith("_selector")
        if is_selector:
            candidates = [tool for tool in native_registry.get_by_capability(native.capability) if tool.name != native.name]
            if selected_tool:
                candidates = [tool for tool in candidates if tool.name == selected_tool]
            if selected_provider != "auto":
                candidates = [tool for tool in candidates if tool.provider.lower() == selected_provider or tool.name.lower() == selected_provider]
            if allowed_providers:
                candidates = [tool for tool in candidates if tool.provider.lower() in allowed_providers or tool.name.lower() in allowed_providers]
            for candidate in candidates:
                options = self._tool_credential_options(candidate, params)
                if options:
                    provider_requirements.setdefault(candidate.provider.lower(), []).extend(options)
        else:
            options = self._tool_credential_options(native, params)
            if options:
                provider_requirements[operation.provider.lower()] = options

        for provider, options in provider_requirements.items():
            raw_credential = await self.database.decrypt_provider_credential(workspace_id, provider)
            if raw_credential is None:
                continue
            env_names = set().union(*options)
            try:
                credential_object = json.loads(raw_credential)
            except json.JSONDecodeError:
                credential_object = None
            if isinstance(credential_object, dict) and credential_object.get("type") == "service_account":
                if "GOOGLE_APPLICATION_CREDENTIALS_JSON" not in env_names or provider not in _GOOGLE_PROVIDER_IDS:
                    raise ValueError("A Google service-account credential can only be used by a Google registry tool")
                values = {"GOOGLE_APPLICATION_CREDENTIALS_JSON": json.dumps(credential_object, separators=(",", ":"))}
            else:
                values = self._decode_provider_values(raw_credential, env_names, options)
            if not is_selector and not any(option.issubset(values) for option in options):
                expected = " or ".join(" + ".join(sorted(option)) for option in options)
                raise ValueError(
                    f"The saved {provider} credential must supply one supported credential set: {expected}. "
                    "Use a JSON object keyed by the environment-variable names shown in the provider setup instructions."
                )
            for name, value in values.items():
                if name in credentials and credentials[name] != value:
                    raise ValueError(f"More than one connected provider supplies {name}; remove the conflicting connection")
                credentials[name] = value

        if not is_selector and provider_requirements and not credentials:
            provider = next(iter(provider_requirements))
            raise ValueError(f"Connect an active {provider} credential in Studio before submitting this job")
        if is_selector and selected_provider != "auto" and not credentials:
            raise ValueError(f"Connect an active {selected_provider} credential in Studio before submitting this job")
        return _hosted_job_environment.set((credentials, managed_names))

    @staticmethod
    def _tool_credential_options(tool, inputs: dict) -> list[set[str]]:
        options = tool.credential_env_options(inputs)
        return [set(option) for option in options if option]

    @staticmethod
    def _decode_provider_values(value: str, allowed_names: set[str], options: list[set[str]]) -> dict[str, str]:
        if value.lstrip().startswith("{"):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("Provider credential JSON is invalid") from exc
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError("Provider credential JSON must be a non-empty object")
            if any(name not in allowed_names for name in parsed):
                raise ValueError("Provider credential JSON contains environment names not declared by the selected tool")
            if any(not isinstance(secret, str) or not secret.strip() for secret in parsed.values()):
                raise ValueError("Every provider credential value must be a non-empty string")
            return {name: secret for name, secret in parsed.items()}
        single_name_options = [next(iter(option)) for option in options if len(option) == 1]
        if single_name_options:
            return {name: value for name in dict.fromkeys(single_name_options)}
        raise ValueError(
            "This provider needs more than one credential field or has multiple key aliases. "
            "Save a JSON object keyed by the environment-variable names shown in the provider setup instructions."
        )

    @staticmethod
    def _managed_environment_names(native_registry) -> set[str]:
        managed: set[str] = set()
        managed.update({
            "STUDIO_CREDENTIAL_ENCRYPTION_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_ACCESS_TOKEN",
            "SUPABASE_DB_PASSWORD",
            "SUPABASE_JWT_SECRET",
            "GOOGLE_APPLICATION_CREDENTIALS",
        })
        # Hosted workers run tenant jobs, so credentials belonging to the MCP
        # service owner must never flow through from the process environment.
        managed.update(
            name for name in os.environ
            if re.search(r"(?:^|_)(?:API_KEY|KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PRIVATE_KEY|ACCESS_KEY)$", name)
        )
        if native_registry is None:
            return managed
        for registered in (native_registry.get(name) for name in native_registry.list_all()):
            for dependency in registered.dependencies:
                if isinstance(dependency, str) and dependency.startswith("env:"):
                    managed.add(dependency[4:])
            for option in registered.credential_env_options():
                managed.update(option)
        return managed


def build_studio_remote(config: dict):
    required = ("supabase_url", "service_role_key", "base_url", "projects_dir", "media_signing_secret")
    if any(not isinstance(config.get(key), str) or not config[key] for key in required):
        raise ValueError("Studio MCP configuration is incomplete")
    origin = urlsplit(config["base_url"])
    if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
            or origin.path not in {"", "/"} or origin.query or origin.fragment):
        raise ValueError("Hosted MCP base_url must be a public HTTPS origin without credentials, path, query, or fragment")
    database = StudioDatabase(config["supabase_url"], config["service_role_key"])
    auth = WorkspaceTokenVerifier(database, config["base_url"].rstrip("/"))
    factory = WorkspaceFactory(config["projects_dir"], database)
    signer = WorkspaceDownloadSigner(config["base_url"], config["media_signing_secret"])
    runner_holder: dict[str, StudioJobRunner] = {}

    @asynccontextmanager
    async def hosted_lifespan(_server):
        runner = runner_holder.get("runner")
        if runner is not None:
            runner.start()
        try:
            yield {}
        finally:
            if runner is not None:
                await runner.stop()

    server = build_server(
        factory, server_class=FastMCP,
        server_options={"auth": auth, "lifespan": hosted_lifespan},
        download_signer=signer,
    )
    middleware = WorkspaceAuthorizationMiddleware(database, server, factory)
    runner_holder["runner"] = middleware.job_runner
    server.add_middleware(middleware)

    @server.custom_route("/download/{ticket}", methods=["GET"], include_in_schema=False)
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
            workspace_token = _workspace_id.set(workspace_id)
            try:
                try:
                    path = signer.media_path(factory, project_id, relative_path)
                except ValueError:
                    path = factory.project(project_id) / relative_path
            finally:
                _workspace_id.reset(workspace_token)
        except (httpx.HTTPError, OSError, ValueError):
            return PlainTextResponse("Link expired or invalid", status_code=404)
        if not path.is_file():
            try:
                signed_url = await database.signed_media_url(workspace_id, project_id, relative_path)
            except (httpx.HTTPError, OSError, ValueError, RuntimeError):
                return PlainTextResponse("Media is unavailable", status_code=404)
            from starlette.responses import RedirectResponse
            return RedirectResponse(signed_url, status_code=302, headers={"Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
        return FileResponse(
            path, filename=path.name, content_disposition_type="inline",
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"},
        )

    @server.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def studio_projects() -> dict:
        """List this MCP token's workspace projects and their creator briefs."""
        access = get_access_token()
        workspace_id = str((access.claims if access else {}).get("workspace_id", ""))
        return {"projects": await database.workspace_projects(workspace_id)}

    @server.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def studio_project_brief(project_id: str) -> dict:
        """Read a creator brief after verifying the project belongs to this workspace."""
        access = get_access_token()
        workspace_id = str((access.claims if access else {}).get("workspace_id", ""))
        project = await database.workspace_project(workspace_id, project_id)
        if project is None:
            raise PermissionError("Project is not available in this workspace")
        brief = project.get("brief") if isinstance(project.get("brief"), dict) else {}
        pipeline = str(brief.get("pipeline") or "animated-explainer")
        from lib.pipeline_loader import list_pipelines
        if pipeline not in list_pipelines():
            pipeline = "animated-explainer"
        return {
            "project": project,
            "next_action": (
                "Initialize this Studio project in the workspace Factory before planning: call "
                "factory_create_project with project_id equal to the Studio project UUID, title equal to the "
                f"saved title, pipeline={pipeline!r}, and config.brief equal to the saved project brief. "
                "Then read that pipeline's manifest and research-stage director instructions, gather cited "
                "sources, and follow the human approval gates. Do not submit generation until its proposal "
                "and required approvals are complete."
            ),
        }

    return server


def main():
    parser = argparse.ArgumentParser(description="Workspace-scoped OpenMontage MCP for Studio")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8769")))
    args = parser.parse_args()
    if args.config.is_symlink() or not args.config.is_file():
        raise ValueError("Configuration must be a regular file")
    if stat.S_IMODE(args.config.stat().st_mode) & 0o077:
        raise ValueError("Configuration contains credentials; set permissions to 600")
    os.umask(0o077)
    config = json.loads(args.config.read_text())
    server = build_studio_remote(config)
    server.run(transport="http", host=config.get("host", "0.0.0.0"), port=args.port, path=config.get("path", "/mcp"))


if __name__ == "__main__":
    main()
