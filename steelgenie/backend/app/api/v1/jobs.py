"""
Jobs router — get job status.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.core.tenancy import AuthUser
from app.schemas.jobs import JobOut
from app.services.database import get_db

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: UUID, user: AuthUser):
    db = get_db()
    resp = db.table("jobs").select("*").eq("id", str(job_id)).maybe_single().execute()
    if not resp or not resp.data:
        raise HTTPException(status_code=404, detail="Job not found")
    return resp.data
