"""
BOM router — GET BOM with filters, basic summary.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from app.core.tenancy import AuthUser
from app.schemas.bom import BomItemOut, BomSummary, ExportRequest
from app.services.database import get_db

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
def get_bom(
    project_id: UUID,
    user: AuthUser,
    category: Optional[str] = Query(None),
    piecemark: Optional[str] = Query(None),
    section_type: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    grade: Optional[str] = Query(None),
    labor_code: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    sequence: Optional[int] = Query(None),
    is_main: Optional[bool] = Query(None),
    sheet: Optional[str] = Query(None, description="Filter to a single drawing/sheet — a project can span multiple uploaded drawings"),
    search: Optional[str] = Query(None, description="Matches piecemark, section, or category"),
    limit: int = Query(10000, le=50000),
    offset: int = Query(0, ge=0),
):
    db = get_db()
    q = db.table("bom_items").select("*").eq("project_id", str(project_id)).order("piecemark")
    if category:
        q = q.eq("category", category)
    if piecemark:
        q = q.ilike("piecemark", f"%{piecemark}%")
    if section_type:
        q = q.eq("section_type", section_type)
    if section:
        q = q.ilike("section", f"%{section}%")
    if grade:
        q = q.eq("grade", grade)
    if labor_code:
        q = q.eq("labor_code", labor_code)
    if status_filter:
        q = q.eq("status", status_filter)
    if sequence is not None:
        q = q.eq("sequence", sequence)
    if is_main is not None:
        q = q.eq("is_main", is_main)
    if search:
        q = q.ilike("piecemark", f"%{search}%")
    q = q.range(offset, offset + limit - 1)
    resp = q.execute()
    items = resp.data or []
    for it in items:
        custom_data = it.get("custom")
        if isinstance(custom_data, dict):
            for k, v in custom_data.items():
                if k not in it or it[k] is None:
                    it[k] = v
    if sheet:
        items = [it for it in items if it.get("sheet") == sheet]
    return items


@router.get("/projects/{project_id}/bom/facets")
def get_bom_facets(project_id: UUID, user: AuthUser):
    """Distinct values per filterable column, for populating the BOM filter sidebar."""
    db = get_db()
    resp = db.table("bom_items").select("*").eq("project_id", str(project_id)).execute()
    items = resp.data or []
    for it in items:
        custom_data = it.get("custom")
        if isinstance(custom_data, dict):
            for k, v in custom_data.items():
                if k not in it or it[k] is None:
                    it[k] = v

    def _distinct(field: str):
        return sorted({str(r[field]) for r in items if r.get(field) not in (None, "")})

    return {
        "category": _distinct("category"),
        "piecemark": _distinct("piecemark"),
        "section_type": _distinct("section_type"),
        "section": _distinct("section"),
        "grade": _distinct("grade"),
        "labor_code": _distinct("labor_code"),
        "status": _distinct("status"),
        "sequence": _distinct("sequence"),
        "sheet": _distinct("sheet"),
    }


@router.get("/projects/{project_id}/bom/summary", response_model=BomSummary)
def get_bom_summary(
    project_id: UUID,
    user: AuthUser,
    sheet: Optional[str] = Query(None, description="Filter to a single drawing/sheet")
):
    db = get_db()
    q = db.table("bom_items").select("*").eq("project_id", str(project_id))
    resp = q.execute()
    items = resp.data or []
    for it in items:
        custom_data = it.get("custom")
        if isinstance(custom_data, dict):
            for k, v in custom_data.items():
                if k not in it or it[k] is None:
                    it[k] = v

    if sheet:
        items = [r for r in items if r.get("sheet") == sheet]

    # Exclude joists from structural steel tonnage total (SJI separate trade scope)
    structural_items = [r for r in items if (r.get("category") or "").lower() != "joists"]
    total_lbs = sum((r.get("weight_lbs") or 0) * (r.get("qty") or 1) for r in structural_items)
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


@router.get("/projects/{project_id}/bom/model-summary")
def get_model_summary(
    project_id: UUID,
    user: AuthUser,
    page_id: Optional[UUID] = Query(None, description="If set, returns a Sheet Summary scoped to this page instead of the whole project"),
):
    """Project Summary / Sheet Summary breakdown for the 3D viewer's
    Properties panel: Column/Beam/VBrace/HBrace/Joists/Moment Connection/
    Bolt/Embed Plate/Camber/Anchor/Weld Studs/Total Weight/Hrs-per-Ton.
    """
    db = get_db()

    sheet_filter: Optional[str] = None
    page_ids_for_moment_count: list[str]
    if page_id:
        page = db.table("pages").select("*").eq("id", str(page_id)).maybe_single().execute().data
        if not page:
            raise HTTPException(status_code=404, detail="Page not found")
        drawing = db.table("drawings").select("*").eq("id", page["drawing_id"]).maybe_single().execute().data
        drawing_filename = (drawing or {}).get("filename") or "Drawing"
        sheet_filter = f"{drawing_filename} — Page {page.get('idx', 0) + 1}"
        page_ids_for_moment_count = [str(page_id)]
    else:
        drawings = db.table("drawings").select("id").eq("project_id", str(project_id)).execute().data or []
        drawing_ids = [d["id"] for d in drawings]
        page_ids_for_moment_count = []
        if drawing_ids:
            pgs = db.table("pages").select("id").in_("drawing_id", drawing_ids).execute().data or []
            page_ids_for_moment_count.extend(p["id"] for p in pgs)

    q = db.table("bom_items").select("*").eq("project_id", str(project_id))
    raw_items = q.execute().data or []
    items = []
    for it in raw_items:
        custom_data = it.get("custom")
        if isinstance(custom_data, dict):
            for k, v in custom_data.items():
                if k not in it or it[k] is None:
                    it[k] = v
        if not sheet_filter or it.get("sheet") == sheet_filter:
            items.append(it)

    def _cat_count(cat: str) -> int:
        return sum((r.get("qty") or 1) for r in items if r.get("category") == cat)

    # Exclude joists from structural steel tonnage total
    structural_items = [r for r in items if (r.get("category") or "").lower() != "joists"]
    total_lbs = sum((r.get("weight_lbs") or 0) * (r.get("qty") or 1) for r in structural_items)
    camber_total = sum((r.get("camber") or 0) * (r.get("qty") or 1) for r in items)
    weld_studs_total = sum((r.get("weld_studs") or 0) for r in items)

    moment_connections = 0
    if page_ids_for_moment_count:
        all_members = db.table("members").select("geometry").in_("page_id", page_ids_for_moment_count).neq("status", "excluded").execute().data or []
        for m in all_members:
            conns = ((m.get("geometry") or {}).get("connections")) or {}
            for side in ("left", "right"):
                if (conns.get(side) or {}).get("type") == "Moment":
                    moment_connections += 1

    anchors_total = 0
    if not page_id:
        groups = db.table("column_groups").select("*").eq("project_id", str(project_id)).execute().data or []
        for g in groups:
            anchors = g.get("anchors")
            if isinstance(anchors, list):
                anchors_total += len(anchors)
            elif isinstance(anchors, dict) and anchors.get("count"):
                anchors_total += int(anchors["count"])

    return {
        "scope": "sheet" if page_id else "project",
        "column": _cat_count("Columns"),
        "beam": _cat_count("Beams"),
        "vertical_brace": _cat_count("Vertical Braces"),
        "horizontal_brace": _cat_count("Horizontal Braces"),
        "joists": _cat_count("Joists"),
        "moment_connection": moment_connections,
        "bolt": _cat_count("Bolts"),
        "embed_plate": 0,
        "camber": round(camber_total, 2),
        "anchor": anchors_total,
        "weld_studs": weld_studs_total,
        "total_weight_tons": round(total_lbs / 2000, 2),
        "hrs_per_ton": None,
    }


@router.post("/projects/{project_id}/bom/generate")
def generate_bom_from_members(project_id: UUID, user: AuthUser):
    """
    Generate BOM rows from current members on all pages.
    This is the M2-level BOM: main members only, weight = lb/ft × length.
    Joists are excluded from structural steel weight (weight_lbs = 0).
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

        # Weight: Joists carry 0 lbs structural steel weight
        wt_per_ft = _section_weight_per_ft(section) if kind != "joist" else 0.0
        weight_lbs = round(wt_per_ft * length_ft, 2) if (wt_per_ft and length_ft) else (0.0 if kind == "joist" else None)

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
            "is_main": kind != "joist",
        })

    if bom_rows:
        for i in range(0, len(bom_rows), 100):
            db.table("bom_items").insert(bom_rows[i:i+100]).execute()

    return {"generated": len(bom_rows)}


@router.get("/projects/{project_id}/bom/export/csv")
def export_bom_csv(project_id: UUID, user: AuthUser):
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
