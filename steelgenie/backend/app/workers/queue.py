"""
Async job queue using asyncio.BackgroundTasks.
No Redis required — jobs run in the FastAPI process.
This is suitable for development and small workloads.
For production, swap out _run_job_async for a Celery/RQ worker call.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, Optional

from app.core.events import manager as ws_manager
from app.services.database import get_db

logger = logging.getLogger(__name__)


async def _update_job(
    job_id: str,
    status: str,
    progress: int = 0,
    message: Optional[str] = None,
    error: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    finished: bool = False,
) -> None:
    """Persist job state to Supabase jobs table."""
    try:
        db = get_db()
        update: Dict[str, Any] = {
            "status": status,
            "progress": progress,
        }
        if message is not None:
            update["message"] = message
        if error is not None:
            update["error"] = error
        if result is not None:
            update["result"] = result
        if status == "running" and not finished:
            update["started_at"] = datetime.now(timezone.utc).isoformat()
        if finished:
            update["finished_at"] = datetime.now(timezone.utc).isoformat()

        db.table("jobs").update(update).eq("id", job_id).execute()
    except Exception as exc:
        logger.error("Failed to update job %s: %s", job_id, exc)


async def create_job(
    job_type: str,
    user_id: str,
    project_id: Optional[str] = None,
    drawing_id: Optional[str] = None,
    page_id: Optional[str] = None,
) -> str:
    """Insert a new job record and return its UUID."""
    db = get_db()
    row: Dict[str, Any] = {
        "type": job_type,
        "status": "queued",
        "progress": 0,
        "created_by": user_id,
    }
    if project_id:
        row["project_id"] = project_id
    if drawing_id:
        row["drawing_id"] = drawing_id
    if page_id:
        row["page_id"] = page_id

    resp = db.table("jobs").insert(row).execute()
    job_id = resp.data[0]["id"]
    logger.info("Job created: %s type=%s", job_id, job_type)
    return job_id


async def dispatch_job(
    background_tasks,          # FastAPI BackgroundTasks
    job_id: str,
    user_id: str,
    coro_fn: Callable[..., Coroutine[Any, Any, None]],
    **kwargs: Any,
) -> None:
    """
    Enqueue *coro_fn* as a background task.
    The function will receive: job_id, user_id, and any **kwargs.
    """
    background_tasks.add_task(_run_job, job_id, user_id, coro_fn, **kwargs)


async def _run_job(
    job_id: str,
    user_id: str,
    coro_fn: Callable[..., Coroutine[Any, Any, None]],
    **kwargs: Any,
) -> None:
    """Execute a job coroutine and update job status accordingly."""
    await _update_job(job_id, "running", 0, "Starting…")
    try:
        await coro_fn(job_id=job_id, user_id=user_id, **kwargs)
        logger.info("Job %s done", job_id)
    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        await _update_job(
            job_id, "failed", 0, error=str(exc), finished=True
        )
        await ws_manager.broadcast_job_done(user_id, job_id, error=str(exc))
