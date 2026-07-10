"""
Build router — triggers the engineering engine for a project.

Gates the Columns/Braces/BOM tabs exactly like the reference product: the
frontend should treat those views as empty/disabled until a build job has
completed at least once (GET /projects/{id}/builds/latest tells it whether
that has happened).
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.core.tenancy import AuthUser
from app.schemas.schedulers import BuildTriggerRequest
from app.services.database import get_db
from app.workers.build import run_build_job
from app.workers.queue import create_job, dispatch_job

logger = logging.getLogger(__name__)
router = APIRouter(tags=["build"])


@router.post("/projects/{project_id}/build", status_code=status.HTTP_202_ACCEPTED)
async def trigger_build(
    project_id: UUID,
    body: BuildTriggerRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser,
):
    db = get_db()
    project = db.table("projects").select("id").eq("id", str(project_id)).maybe_single().execute()
    if not project or not project.data:
        raise HTTPException(status_code=404, detail="Project not found")

    job_id = await create_job("build", user.id, project_id=str(project_id))
    await dispatch_job(
        background_tasks, job_id, user.id,
        run_build_job,
        project_id=str(project_id),
        page_ids=[str(p) for p in body.page_ids] if body.page_ids else None,
    )
    return {"job_id": job_id}


@router.get("/projects/{project_id}/builds/latest")
async def get_latest_build(project_id: UUID, user: AuthUser):
    """Used by the frontend to decide whether to gate Columns/Braces/BOM tabs."""
    db = get_db()
    resp = (
        db.table("jobs")
        .select("*")
        .eq("project_id", str(project_id))
        .eq("type", "build")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        return {"has_build": False, "job": None}
    return {"has_build": rows[0].get("status") == "done", "job": rows[0]}
