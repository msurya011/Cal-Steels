"""
Members router — CRUD + bulk operations for structural members.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.core.tenancy import AuthUser
from app.schemas.jobs import AnalyseRequest
from app.schemas.members import MemberBulkDelete, MemberBulkUpdate, MemberCreate, MemberOut, MemberUpdate
from app.services.database import get_db
from app.workers.analyse import run_analyse
from app.workers.queue import create_job, dispatch_job

logger = logging.getLogger(__name__)
router = APIRouter(tags=["members"])


def _kind_from_type(t: str) -> str:
    mapping = {"beam": "beam", "column": "column", "brace": "vbrace",
               "vertical_brace": "vbrace", "horizontal_brace": "hbrace",
               "joist": "joist"}
    return mapping.get(t, "beam")


@router.get("/pages/{page_id}/members", response_model=List[MemberOut])
async def list_members(
    page_id: UUID,
    user: AuthUser,
    kind: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
):
    db = get_db()
    q = db.table("members").select("*").eq("page_id", str(page_id))
    if kind:
        q = q.eq("kind", kind)
    if status_filter:
        q = q.eq("status", status_filter)
    resp = q.execute()
    return resp.data or []


@router.get("/pages/{page_id}/members/summary")
async def get_members_summary(page_id: UUID, user: AuthUser):
    db = get_db()
    resp = db.table("members").select("kind, status").eq("page_id", str(page_id)).execute()
    members = resp.data or []
    
    counts_by_kind = {"beam": 0, "column": 0, "vbrace": 0, "hbrace": 0, "joist": 0}
    counts_by_status = {"active": 0, "need_review": 0, "verified": 0, "rejected": 0, "excluded": 0}
    
    for m in members:
        k = m.get("kind", "beam")
        s = m.get("status", "active")
        
        # Normalize kind if needed
        if k == "vertical_brace":
            k = "vbrace"
        elif k == "horizontal_brace":
            k = "hbrace"
            
        if k in counts_by_kind:
            counts_by_kind[k] += 1
        else:
            counts_by_kind[k] = 1
            
        if s in counts_by_status:
            counts_by_status[s] += 1
        else:
            counts_by_status[s] = 1
            
    total = len(members)
    return {
        "counts_by_kind": counts_by_kind,
        "counts_by_status": counts_by_status,
        "total_count": total,
    }


@router.post("/pages/{page_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def create_member(page_id: UUID, body: MemberCreate, user: AuthUser):
    db = get_db()
    row = {
        "page_id": str(page_id),
        "kind": body.kind,
        "section": body.section,
        "grade": body.grade,
        "rotation": body.rotation,
        "status": body.status,
        "source": "manual",
        "geometry": body.geometry,
        "length_ft": body.length_ft,
        "created_by": user.id,
    }
    resp = db.table("members").insert(row).execute()
    return resp.data[0]


@router.patch("/members/{member_id}", response_model=MemberOut)
async def update_member(member_id: UUID, body: MemberUpdate, user: AuthUser):
    db = get_db()
    update = body.model_dump(exclude_none=True)
    if "status" in update and update["status"] in ("verified", "rejected", "active", "need_review"):
        update["reviewed_by"] = str(user.id)
        update["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    resp = db.table("members").update(update).eq("id", str(member_id)).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Member not found")
    return resp.data[0]


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(member_id: UUID, user: AuthUser):
    db = get_db()
    db.table("members").delete().eq("id", str(member_id)).execute()


@router.post("/members/bulk-update", response_model=List[MemberOut])
async def bulk_update_members(body: MemberBulkUpdate, user: AuthUser):
    db = get_db()
    update = body.update.model_dump(exclude_none=True)
    if "status" in update and update["status"] in ("verified", "rejected", "active", "need_review"):
        update["reviewed_by"] = str(user.id)
        update["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    ids = [str(i) for i in body.ids]
    resp = db.table("members").update(update).in_("id", ids).execute()
    return resp.data or []


@router.post("/members/bulk-delete", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_delete_members(body: MemberBulkDelete, user: AuthUser):
    db = get_db()
    ids = [str(i) for i in body.ids]
    db.table("members").delete().in_("id", ids).execute()


@router.post("/pages/{page_id}/analyse", status_code=status.HTTP_202_ACCEPTED)
async def analyse_page(
    page_id: UUID,
    body: AnalyseRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser,
):
    """Trigger member extraction for a page. Returns a job_id to track progress."""
    db = get_db()

    # Get page and drawing info.
    # NOTE: do NOT rely on the PostgREST nested join ("drawings(...)") — the
    # local mock DB doesn't implement joins, which yielded drawing_id=None.
    page_row = db.table("pages").select("*").eq("id", str(page_id)).single().execute()
    if not page_row.data:
        raise HTTPException(status_code=404, detail="Page not found")

    page = page_row.data
    drawing_id = (page.get("drawings") or {}).get("id") or page.get("drawing_id")
    if not drawing_id:
        raise HTTPException(status_code=404, detail="Page has no parent drawing")

    drawing_row = db.table("drawings").select("*").eq("id", str(drawing_id)).single().execute()
    if not drawing_row.data:
        raise HTTPException(status_code=404, detail="Drawing not found")
    project_id = drawing_row.data.get("project_id")

    if not body.scale_ratio:
        raise HTTPException(status_code=400, detail="scale_ratio is required")

    job_id = await create_job("analyse", user.id, project_id, drawing_id, str(page_id))
    await dispatch_job(
        background_tasks, job_id, user.id,
        run_analyse,
        page_id=str(page_id),
        drawing_id=drawing_id,
        project_id=project_id,
        scale_ratio=body.scale_ratio,
        detect_braces=body.detect_braces,
        detect_unlabeled=body.detect_unlabeled,
        ocr_dpi=body.ocr_dpi,
        floor_elevation_ft=body.floor_elevation_ft,
    )

    return {"job_id": job_id}
