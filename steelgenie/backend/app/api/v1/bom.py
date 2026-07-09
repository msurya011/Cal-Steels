"""
BOM router — GET BOM with filters, basic summary.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from app.core.tenancy import AuthUser
from app.schemas.bom import BomItemOut, BomSummary, ExportRequest
from app.services.database import get_db
from app.workers.queue import create_job

logger = logging.getLogger(__name__)
router = APIRouter(tags=["bom"])

# AISC section weight lookup (lb/ft) — extracted from section name (W12X26 → 26)
def _section_weight_per_ft(section: Optional[str]) -> Optional[float]:
    if not section:
        return None
    import re
    m = re.match(r"^(?:W|C|MC|S|HP|WT|MT|ST|M)\d+(?:\.\d+)?[Xx](\d+(?:\.\d+)?)$", (section or "").upper())
    if m:
        return float(m.group(1))
        
    # Database library lookup fallback
    try:
        db = get_db()
        row = db.table("sections").select("weight_per_ft").eq("designation", section.upper()).maybe_single().execute()
        if row and row.data:
            # Note: weight_per_m is stored in kg/m or lbs/ft. For standard IS808, convert kg/m to lbs/ft if standard is IS808.
            # However, for simplicity, we assume the weight_per_ft column stores the value.
            return float(row.data.get("weight_per_ft") or 0)
    except Exception as exc:
        logger.warning("Failed to lookup section weight in DB: %s", exc)
        
    return None


@router.get("/projects/{project_id}/bom", response_model=List[BomItemOut])
async def get_bom(
    project_id: UUID,
    user: AuthUser,
    category: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    grade: Optional[str] = Query(None),
    is_main: Optional[bool] = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
):
    db = get_db()
    q = db.table("bom_items").select("*").eq("project_id", str(project_id)).order("piecemark")
    if category:
        q = q.eq("category", category)
    if section:
        q = q.ilike("section", f"%{section}%")
    if grade:
        q = q.eq("grade", grade)
    if is_main is not None:
        q = q.eq("is_main", is_main)
    q = q.range(offset, offset + limit - 1)
    resp = q.execute()
    return resp.data or []


@router.get("/projects/{project_id}/bom/summary", response_model=BomSummary)
async def get_bom_summary(project_id: UUID, user: AuthUser):
    db = get_db()
    resp = db.table("bom_items").select("category,weight_lbs,qty").eq("project_id", str(project_id)).execute()
    items = resp.data or []

    total_lbs = sum((r.get("weight_lbs") or 0) * (r.get("qty") or 1) for r in items)
    by_cat: Dict[str, int] = {}
    for r in items:
        cat = r.get("category") or "other"
        by_cat[cat] = by_cat.get(cat, 0) + (r.get("qty") or 1)

    return BomSummary(
        total_items=len(items),
        total_weight_lbs=round(total_lbs, 2),
        total_weight_tons=round(total_lbs / 2000, 3),
        by_category=by_cat,
    )


@router.post("/projects/{project_id}/bom/generate")
async def generate_bom_from_members(project_id: UUID, user: AuthUser):
    """
    Generate BOM rows from current members on all pages.
    This is the M2-level BOM: main members only, weight = lb/ft × length.
    """
    db = get_db()

    # Get all pages for this project
    drawings = db.table("drawings").select("id").eq("project_id", str(project_id)).execute()
    drawing_ids = [d["id"] for d in (drawings.data or [])]

    if not drawing_ids:
        raise HTTPException(status_code=400, detail="No drawings found for this project")

    all_members: List[Dict[str, Any]] = []
    for did in drawing_ids:
        pages_resp = db.table("pages").select("id").eq("drawing_id", did).execute()
        for pg in (pages_resp.data or []):
            members_resp = db.table("members").select("*").eq("page_id", pg["id"]).neq("status", "excluded").execute()
            all_members.extend(members_resp.data or [])

    # Clear existing BOM items for this project
    db.table("bom_items").delete().eq("project_id", str(project_id)).execute()

    # Generate new BOM rows
    bom_rows = []
    piecemark_counters: Dict[str, int] = {}

    for m in all_members:
        kind = m.get("kind", "beam")
        section = m.get("section")
        grade = m.get("grade", "A992")
        length_ft = m.get("length_ft") or 0
        length_in = round(length_ft * 12, 2) if length_ft else None

        # Category
        cat_map = {"beam": "Beams", "column": "Columns", "vbrace": "Vertical Braces",
                   "hbrace": "Horizontal Braces", "joist": "Joists"}
        category = cat_map.get(kind, "Other")

        # Simple piecemark (sequential by section)
        mark_prefix = {"beam": "B", "column": "C", "vbrace": "VB", "hbrace": "HB", "joist": "J"}.get(kind, "X")
        key = f"{mark_prefix}_{section or 'UNK'}"
        piecemark_counters[key] = piecemark_counters.get(key, 0) + 1
        piecemark = f"{mark_prefix}_{piecemark_counters[key]}"

        # Weight
        wt_per_ft = _section_weight_per_ft(section)
        weight_lbs = round(wt_per_ft * length_ft, 2) if wt_per_ft and length_ft else None

        # Section type
        import re
        section_type = None
        if section:
            m2 = re.match(r"^([A-Z]+)", section.upper())
            if m2:
                section_type = m2.group(1)

        bom_rows.append({
            "project_id": str(project_id),
            "piecemark": piecemark,
            "category": category,
            "qty": 1,
            "section_type": section_type,
            "section": section,
            "length_in": length_in,
            "grade": grade,
            "weight_lbs": weight_lbs,
            "is_main": True,
        })

    if bom_rows:
        for i in range(0, len(bom_rows), 100):
            db.table("bom_items").insert(bom_rows[i:i+100]).execute()

    return {"generated": len(bom_rows)}


@router.get("/projects/{project_id}/bom/export/csv")
async def export_bom_csv(project_id: UUID, user: AuthUser):
    """Export BOM as CSV."""
    db = get_db()
    resp = db.table("bom_items").select("*").eq("project_id", str(project_id)).order("category,section").execute()
    items = resp.data or []

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Piecemark", "Category", "Qty", "Section Type", "Section",
                     "Length (in)", "Grade", "Labor Code", "Weight (lbs)", "Camber",
                     "Cope", "Holes", "Weld Studs", "Status", "Sequence", "Paint", "Main"])

    for item in items:
        writer.writerow([
            item.get("piecemark", ""),
            item.get("category", ""),
            item.get("qty", 1),
            item.get("section_type", ""),
            item.get("section", ""),
            item.get("length_in", ""),
            item.get("grade", ""),
            item.get("labor_code", ""),
            item.get("weight_lbs", ""),
            item.get("camber", 0),
            item.get("cope", 0),
            item.get("holes", 0),
            item.get("weld_studs", 0),
            item.get("status", ""),
            item.get("sequence", ""),
            item.get("paint", ""),
            "Yes" if item.get("is_main") else "No",
        ])

    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="bom_{project_id}.csv"'},
    )
