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


@router.post("/pages/{page_id}/columns/validate", status_code=status.HTTP_200_OK)
async def validate_page_columns(page_id: UUID, user: AuthUser):
    """
    Re-evaluate column validation rules (grid snapping, orphan checking) on demand.
    This is triggered by the frontend after a manual column drag-and-drop.
    """
    db = get_db()
    # In a full implementation, we would query all grid lines and columns for the page,
    # recompute intersections, and update the error_flags in the geometry JSON.
    # For now, we return 200 OK to acknowledge the frontend update.
    return {"status": "ok"}



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


@router.post("/pages/{page_id}/columns/validate")
async def validate_page_columns(
    page_id: UUID,
    user: AuthUser,
):
    """Re-run column validation scoring and update status/error flags in DB."""
    import math
    db = get_db()
    
    # 1. Fetch all members on the page
    res = db.table("members").select("*").eq("page_id", str(page_id)).execute()
    if not res.data:
        return {"updated": 0}
    
    members = res.data
    columns = [m for m in members if m.get("type") == "column"]
    beams = [m for m in members if m.get("type") == "beam"]
    
    # Derive idealized grids from column locations
    v_xs = [m.get("x") for m in columns if m.get("x") is not None]
    h_ys = [m.get("y") for m in columns if m.get("y") is not None]
    
    def _cluster(vals, tol=0.015):
        out = []
        for v in sorted(vals):
            if not out or v - out[-1] > tol:
                out.append(v)
        return out
    
    v_grid = _cluster(v_xs)
    h_grid = _cluster(h_ys)
    
    # Collect beam endpoints
    beam_ends = []
    for m in beams:
        geom = m.get("geometry") or {}
        bx1 = geom.get("bx1") or m.get("bx1")
        by1 = geom.get("by1") or m.get("by1")
        bx2 = geom.get("bx2") or m.get("bx2")
        by2 = geom.get("by2") or m.get("by2")
        if bx1 is not None and by1 is not None:
            beam_ends.append((bx1, by1))
        if bx2 is not None and by2 is not None:
            beam_ends.append((bx2, by2))
            
    updated_count = 0
    
    for col in columns:
        cx, cy = col.get("x"), col.get("y")
        if cx is None or cy is None:
            continue
        geom = col.get("geometry") or {}
        raw_x = geom.get("raw_x", cx)
        raw_y = geom.get("raw_y", cy)
        
        # Grid snaps
        off_grid = True
        gx, gy = None, None
        if v_grid:
            gx = min(v_grid, key=lambda g: abs(cx - g))
            if abs(cx - gx) <= 0.015:
                off_grid = False
        if h_grid:
            gy = min(h_grid, key=lambda g: abs(cy - g))
            if abs(cy - gy) <= 0.015:
                off_grid = False
                
        # Beam support
        close_ends = [(ex, ey) for ex, ey in beam_ends if math.hypot(cx - ex, cy - ey) < 0.025]
        unique_ends = []
        for (ex, ey) in close_ends:
            if not any(math.hypot(ex - ux, ey - uy) < 0.005 for ux, uy in unique_ends):
                unique_ends.append((ex, ey))
                
        has_label_match = col.get("profile") not in ("COL", "", None)
        
        score = 0.0
        if has_label_match:
            score += 0.40
        if not off_grid:
            score += 0.30
        if len(unique_ends) >= 2:
            score += 0.20
        if geom.get("symbol") in ("I", "BOX", "PIPE"):
            score += 0.10
            
        status = 'active' if score >= 0.75 else 'need_review'
        
        error_flags = []
        if off_grid:
            error_flags.append("no_grid")
        if not has_label_match:
            error_flags.append("no_label")
        if len(unique_ends) < 2:
            error_flags.append("orphan")
            
        v_idx = sorted(v_grid).index(gx) + 1 if v_grid and gx is not None and gx in v_grid else "?"
        h_idx = sorted(h_grid).index(gy) + 1 if h_grid and gy is not None and gy in h_grid else "?"
        grid_ref = f"{v_idx}-{h_idx}" if (v_idx != "?" or h_idx != "?") else None

        new_geom = {
            **geom,
            "x": cx,
            "y": cy,
            "raw_x": raw_x,
            "raw_y": raw_y,
            "off_grid": off_grid,
            "error_flags": error_flags,
            "grid_ref": grid_ref,
        }
        
        db.table("members").update({
            "status": status,
            "geometry": new_geom
        }).eq("id", col["id"]).execute()
        updated_count += 1
        
    return {"updated": updated_count}

