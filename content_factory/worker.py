"""Persistent job supervisor. Executes one operation; never plans or advances stages."""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def supervise(root: Path, project: str, job_id: str):
    db = sqlite3.connect(root / project / "factory.sqlite3", timeout=30)
    row = db.execute("SELECT status, data FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise ValueError("Unknown job")
    if row[0] == "cancelling":
        db.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (job_id,))
        db.commit()
        return
    # Claim once even if the supervisor is accidentally launched twice.
    changed = db.execute("UPDATE jobs SET status='running', pid=? WHERE id=? AND status='queued'", (os.getpid(), job_id)).rowcount
    db.commit()
    if not changed:
        return
    data = json.loads(row[1])
    output = root / project / "artifacts/factory-jobs" / f"{job_id}.json"
    child = None
    try:
        child = subprocess.Popen([sys.executable, "-m", "content_factory.worker", str(root), project, job_id, "--execute"], start_new_session=True)
        deadline = time.monotonic() + data["timeout_seconds"]
        status = None
        while child.poll() is None:
            cancelled = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()[0] == "cancelling"
            if cancelled or time.monotonic() >= deadline:
                status = "cancelled" if cancelled else "timed_out"
                # Stop the full local process tree, including renderer subprocesses.
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
                break
            time.sleep(.2)
        if status:
            result = {"success": False, "error": status, "note": "Remote provider work may continue. Inspect provider status before resubmitting; no automatic retry."}
        elif output.exists():
            result = json.loads(output.read_text())
            status = "completed" if child.returncode == 0 and result.get("success") else "failed"
        else:
            status, result = "failed", {"success": False, "error": f"Worker exited {child.returncode} without a result; inspect log."}
    except Exception as exc:
        status, result = "failed", {"success": False, "error": str(exc)}
        if child and child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
    from content_factory.automation import init, settle
    init(db)
    try:
        settle(db, job_id, result.get("cost_usd") if status == "completed" else None)
    except (ValueError, TypeError):
        settle(db, job_id, None)
        result["cost_warning"] = "Provider returned an invalid cost; reservation retained"
    db.execute("UPDATE jobs SET status=?, result=? WHERE id=?", (status, json.dumps(result, default=str), job_id))
    db.commit()
    db.close()


def execute(root: Path, project: str, job_id: str):
    from content_factory.registry import Registry
    db = sqlite3.connect(root / project / "factory.sqlite3")
    data = json.loads(db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()[0])
    db.close()
    try:
        plugin, op = Registry().resolve(data["step"]["operation"])
        if plugin.manifest.version != data["step"]["plugin_version"] or op.version != data["step"]["operation_version"]:
            raise ValueError("Plugin changed after submission; operation was not executed")
        result = plugin.execute(op.id, data["step"]["params"])
    except Exception as exc:
        result = {"success": False, "error": str(exc)}
    path = root / project / "artifacts/factory-jobs" / f"{job_id}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, default=str))
    temporary.replace(path)


if __name__ == "__main__":
    root, project, job_id = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    if "--execute" in sys.argv:
        execute(root, project, job_id)
    else:
        supervise(root, project, job_id)
