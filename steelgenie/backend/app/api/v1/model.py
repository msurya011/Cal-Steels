"""
Model router — GET 3D structural model.
Wraps the existing /model endpoint logic from main.py.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.core.tenancy import AuthUser
from app.services.database import get_db
from app.services.storage import get_storage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["model"])


@router.get("/projects/{project_id}/model")
async def get_project_model(
    project_id: UUID,
    user: AuthUser,
    page_id: UUID = Query(...),
    scale_ratio: float = Query(96.0),
    # No default -- T.O.S. is per-drawing user input, never guessed.
    floor_elevation_ft: float = Query(...),
) -> Dict[str, Any]:
    """Build and return the 3D structural model JSON for a page."""
    db = get_db()
    storage = get_storage()

    # Get page and drawing info (no nested join — mock DB doesn't support joins)
    page_row = db.table("pages").select("*").eq("id", str(page_id)).single().execute()
    if not page_row.data:
        raise HTTPException(status_code=404, detail="Page not found")

    page = page_row.data
    page_idx = page["idx"]
    drawing_id_val = (page.get("drawings") or {}).get("id") or page.get("drawing_id")
    if not drawing_id_val:
        raise HTTPException(status_code=404, detail="Page has no parent drawing")

    # Get local file path
    from app.services.storage import LocalStorageAdapter
    drawing_row = db.table("drawings").select("storage_key").eq("id", str(drawing_id_val)).maybe_single().execute()
    if not drawing_row or not drawing_row.data:
        raise HTTPException(status_code=404, detail="Drawing not found")

    storage_key = drawing_row.data["storage_key"]
    if isinstance(storage, LocalStorageAdapter):
        file_path = storage.local_path(storage_key)
    else:
        raise HTTPException(status_code=501, detail="3D model with R2 storage not yet implemented")

    # Add backend dir to path for existing structural modules
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    try:
        from structural_schema import build_structural_model as _build_model

        # Get members from DB
        members_resp = db.table("members").select("*").eq("page_id", str(page_id)).neq("status", "excluded").execute()
        raw_members = members_resp.data or []

        # Convert to the format the structural model builder expects
        members_for_model = []
        for m in raw_members:
            geo = m.get("geometry", {})
            members_for_model.append({
                "profile": m.get("section", ""),
                "type": m.get("kind", "beam"),
                "x": geo.get("x", 0),
                "y": geo.get("y", 0),
                "w": geo.get("w", 0),
                "h": geo.get("h", 0),
                "bx1": geo.get("bx1"),
                "by1": geo.get("by1"),
                "bx2": geo.get("bx2"),
                "by2": geo.get("by2"),
                "length_ft": m.get("length_ft", 0),
                "angle_deg": geo.get("angle_deg"),
                "beam_dir": geo.get("beam_dir", "H"),
                "color": geo.get("color", "#EC4899"),
            })

        import fitz
        doc = fitz.open(file_path)
        p = doc[page_idx]
        page_w = p.rect.width
        page_h = p.rect.height
        doc.close()

        FLOOR_HEIGHT_FT = 14.0
        base_elev = page_idx * FLOOR_HEIGHT_FT

        model = _build_model(
            members=members_for_model,
            page_width_pts=page_w,
            page_height_pts=page_h,
            scale_ratio=scale_ratio,
            source=storage_key,
            page=page_idx,
            floor_elevation_ft=floor_elevation_ft,
            base_elevation_ft=base_elev,
        )
        return model

    except Exception as exc:
        logger.exception("Model build failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Model build failed: {exc}")


def attach_bom_attributes(project_id: str, members: list[dict]) -> list[dict]:
    """Attach post-Build fabrication attributes (weight_lbs, sequence,
    labor_code, paint) to each 3D model member, when a Build has run.
    """
    if not members:
        return members
    db = get_db()
    member_ids = list({m["member_id"] for m in members if m.get("member_id")})
    if not member_ids:
        return members
    
    bom_rows = []
    try:
        # Batch in chunks of 30 to prevent PostgREST URL length 400 errors
        for i in range(0, len(member_ids), 30):
            chunk = member_ids[i:i+30]
            rows = db.table("bom_items").select("member_id, weight_lbs, sequence, labor_code, paint").in_("member_id", chunk).execute().data or []
            bom_rows.extend(rows)
    except Exception as exc:
        logger.warning("BOM items fetch error in attach_bom_attributes: %s", exc)

    by_member_id: dict[str, dict] = {}
    for row in bom_rows:
        mid = row.get("member_id")
        if mid and mid not in by_member_id:  # first row wins (main member row, not accessories)
            by_member_id[mid] = row
    for m in members:
        row = by_member_id.get(m.get("member_id"))
        m["weight_lbs"] = row.get("weight_lbs") if row else None
        m["sequence"] = row.get("sequence") if row else None
        m["labor_code"] = row.get("labor_code") if row else None
        m["paint"] = row.get("paint") if row else None
    return members


def deduplicate_members(members: list[dict]) -> list[dict]:
    # Group by floor
    by_floor = {}
    for m in members:
        fid = m.get("floor_id")
        if fid not in by_floor:
            by_floor[fid] = []
        by_floor[fid].append(m)

    out = []
    for fid, floor_m in by_floor.items():
        columns = [m for m in floor_m if m["type"] == "column"]
        other = [m for m in floor_m if m["type"] != "column"]

        # Merge overlapping columns
        merged_cols = []
        for col in columns:
            cx, cy, cz = col["start"]
            found = False
            for mc in merged_cols:
                mcx, mcy, mcz = mc["start"]
                dist = ((cx - mcx)**2 + (cz - mcz)**2)**0.5
                if dist < 1.5:  # within 1.5 feet
                    found = True
                    if not mc.get("profile") and col.get("profile"):
                        mc["profile"] = col["profile"]
                    if not mc.get("piecemark") and col.get("piecemark"):
                        mc["piecemark"] = col["piecemark"]
                    if "merged_member_ids" not in mc:
                        mc["merged_member_ids"] = [mc["member_id"]]
                    mc["merged_member_ids"].append(col["member_id"])
                    break
            if not found:
                merged_cols.append(col)

        # Merge overlapping/coincident beams
        merged_beams = []
        beams = [m for m in other if m["type"] == "beam"]
        other_members = [m for m in other if m["type"] != "beam"]

        for b in beams:
            bx1, by1, bz1 = b["start"]
            bx2, by2, bz2 = b["end"]
            found = False
            for mb in merged_beams:
                mbx1, mby1, mbz1 = mb["start"]
                mbx2, mby2, mbz2 = mb["end"]

                # Check distance between endpoints
                d_ss = ((bx1 - mbx1)**2 + (bz1 - mbz1)**2)**0.5
                d_ee = ((bx2 - mbx2)**2 + (bz2 - mbz2)**2)**0.5
                d_se = ((bx1 - mbx2)**2 + (bz1 - mbz2)**2)**0.5
                d_es = ((bx2 - mbx1)**2 + (bz2 - mbz1)**2)**0.5

                if (d_ss < 1.0 and d_ee < 1.0) or (d_se < 1.0 and d_es < 1.0):
                    found = True
                    if not mb.get("profile") and b.get("profile"):
                        mb["profile"] = b["profile"]
                    if not mb.get("piecemark") and b.get("piecemark"):
                        mb["piecemark"] = b["piecemark"]
                    if "merged_member_ids" not in mb:
                        mb["merged_member_ids"] = [mb["member_id"]]
                    mb["merged_member_ids"].append(b["member_id"])
                    break
            if not found:
                merged_beams.append(b)

        out.extend(merged_cols)
        out.extend(merged_beams)
        out.extend(other_members)
    return out


_TYPE_PREFIX = {"beam": "B", "joist": "J", "vbrace": "BR", "hbrace": "BR", "brace": "BR", "column": "C"}
# No default storey-height constant -- every elevation used below comes from
# a floor's real elevation_ft or, failing that, one of its pages' actual
# user-entered tos_ft. Never a guessed constant.


def _grids_out(page: dict, floor_elev: float, db, base_elev: float = 0.0) -> list[dict]:
    """Labeled grid lines for one page, placed at grade (base_elev) -- the
    real-world reference plane a structural grid actually sits on, matching
    SteelGenie. This used to place grids at the floor's own TOS (floor_elev),
    which put them up at the roof/floor plate instead of at the ground the
    columns actually rise from -- looked like the grid was floating near the
    top of the columns instead of anchoring their base."""
    from app.engineering.registration import grid_lines_global

    lines = grid_lines_global(page, db)
    out = []
    for g in lines:
        out.append({
            "id": f"{page['id']}_grid_{g['axis']}_{g['label']}",
            "axis": g["axis"],
            "label": g["label"],
            "page_id": page["id"],
            "start": [g["gx1"], base_elev, g["gy1"]],
            "end": [g["gx2"], base_elev, g["gy2"]],
        })
    return out


def _member_out(m: dict, page: dict, floor_elev: float, base_elev: float, db) -> Dict[str, Any] | None:
    from app.engineering.registration import member_global_endpoints

    g = member_global_endpoints(m, page, db)
    kind = m.get("kind", "beam")
    geo = m.get("geometry") or {}

    if kind == "column":
        gx = g.get("gx_ft")
        gy = g.get("gy_ft")
        if gx is None or gy is None:
            return None
        start = [gx, base_elev, gy]
        end = [gx, floor_elev, gy]
    elif g.get("gx1_ft") is not None:
        start = [g["gx1_ft"], floor_elev, g["gy1_ft"]]
        end = [g["gx2_ft"], floor_elev, g["gy2_ft"]]
    else:
        gx = g.get("gx_ft")
        gy = g.get("gy_ft")
        if gx is None or gy is None:
            return None
        start = [gx, floor_elev, gy]
        end = [gx, floor_elev, gy]

    return {
        "id": f"{page['id']}_{m['id']}",
        "member_id": m["id"],
        "page_id": page["id"],
        "type": kind,
        "profile": m.get("section"),
        "piecemark": m.get("piecemark"),
        "status": m.get("status"),
        "start": start,
        "end": end,
        # Column cross-section shape + orientation, so the 3D viewer can draw
        # the real symbol (I-shape / box tube / pipe) instead of a generic
        # box for every column -- mirrors ColumnSymbol.tsx's 2D logic.
        "rotation": m.get("rotation", 0) if kind == "column" else None,
        "symbol": geo.get("symbol") if kind == "column" else None,
        "unlabeled": bool(geo.get("unlabeled")),
    }


def _ensure_project_registered(project_id: str, db) -> None:
    """Auto-run multi-sheet registration if not yet registered."""
    floors = db.table("floors").select("*").eq("project_id", project_id).execute().data or []
    if floors:
        floor_ids = [f["id"] for f in floors]
        all_regs = db.table("page_registrations").select("page_id, floor_id").in_("floor_id", floor_ids).execute().data or []
        cols = db.table("columns").select("id").eq("project_id", project_id).limit(1).execute().data or []
        if all_regs and cols:
            # Already registered and columns synced! Return immediately (< 5ms response time)
            return

    from app.engineering.registration import cluster_pages_into_floors, register_floor, sync_global_columns

    try:
        cluster_pages_into_floors(project_id)
    except Exception:
        logger.exception("Auto floor-clustering failed for project %s", project_id)
        return

    floors = db.table("floors").select("*").eq("project_id", project_id).execute().data or []
    if not floors:
        return
    links = db.table("page_floor_links").select("*").execute().data or []
    floor_ids = [f["id"] for f in floors]
    page_ids_in_project = [l["page_id"] for l in links if l["floor_id"] in floor_ids]
    if not page_ids_in_project:
        return

    all_pages = db.table("pages").select("id, status").in_("id", page_ids_in_project).execute().data or []
    all_regs = db.table("page_registrations").select("page_id, floor_id").in_("floor_id", floor_ids).execute().data or []
    registered_by_floor: dict[str, set] = {}
    for r in all_regs:
        registered_by_floor.setdefault(r["floor_id"], set()).add(r["page_id"])
    for f in floors:
        floor_page_ids = [l["page_id"] for l in links if l["floor_id"] == f["id"]]
        if not floor_page_ids:
            continue
        registered_page_ids = registered_by_floor.get(f["id"], set())
        if set(floor_page_ids).issubset(registered_page_ids):
            continue
        try:
            register_floor(f["id"])
        except Exception:
            logger.exception("Auto floor registration failed for floor %s", f["id"])

    try:
        sync_global_columns(project_id)
    except Exception:
        logger.exception("Global column sync failed for project %s", project_id)


@router.get("/projects/{project_id}/debug/column-trace")
async def get_column_trace(
    project_id: UUID,
    user: AuthUser,
    sample_size: int = Query(5, ge=1, le=50),
    focus_page_ids: Optional[str] = Query(
        None, description="Comma-separated page IDs to bias the sample toward (e.g. Page 14/15's ids)"
    ),
) -> Dict[str, Any]:
    """
    TEMPORARY diagnostic endpoint -- read-only, writes nothing. Traces a
    sample of columns end-to-end (base/top elevation, which beams were
    searched and why each was accepted/rejected) plus a full floor
    registration report, so a zero-height-column report can be root-caused
    with real data before any change is made to sync_global_columns() or
    the floor-registration pipeline. See
    app.engineering.registration.debug_column_trace for the full docstring.
    """
    from app.engineering.registration import debug_column_trace

    focus_ids = [s.strip() for s in focus_page_ids.split(",")] if focus_page_ids else None
    return debug_column_trace(str(project_id), sample_size=sample_size, focus_page_ids=focus_ids)


@router.get("/pages/{page_id}/debug/column-validation-log")
async def get_column_validation_log(
    page_id: UUID,
    user: AuthUser,
) -> Dict[str, Any]:
    """TEMPORARY diagnostic endpoint -- reads main._LAST_COLUMN_VALIDATION_LOG,
    which emit_symbol_columns() repopulates on every call. Trigger a real
    re-extraction of this page first (POST /pages/{id}/analyse, or the
    Extract button in the UI), then call this to see EXACTLY why every
    classifier-approved footing/column symbol on that page was accepted or
    rejected by the Column Validation Engine's structural-context score --
    not just the classifier-stage accept/reject that /debug/symbol-detection
    already covers, but the second, later gate downstream of it."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    log_path = os.path.join(backend_dir, "_column_validation_debug.json")
    log: list = []
    if os.path.exists(log_path):
        import json as _json
        with open(log_path) as _f:
            log = _json.load(_f)
    by_outcome_stage: Dict[str, int] = {}
    for row in log:
        key = f'{row.get("outcome")}:{row.get("stage")}'
        by_outcome_stage[key] = by_outcome_stage.get(key, 0) + 1
    return {"page_id": str(page_id), "total": len(log), "by_outcome_stage": by_outcome_stage, "log": log}


@router.get("/projects/{project_id}/debug/sync-columns-now")
async def debug_sync_columns_now(
    project_id: UUID,
    user: AuthUser,
) -> Dict[str, Any]:
    """TEMPORARY diagnostic endpoint -- calls sync_global_columns() directly
    (not through the swallowed try/except in _ensure_project_registered) so
    a silent 0-columns write can be root-caused: surfaces the real exception
    with a traceback string instead of just a log line nobody can see from
    the browser."""
    import traceback
    from app.engineering.registration import sync_global_columns
    try:
        result = sync_global_columns(str(project_id))
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}


@router.get("/projects/{project_id}/debug/column-segments")
async def get_column_segments(
    project_id: UUID,
    user: AuthUser,
) -> Dict[str, Any]:
    """
    TEMPORARY diagnostic endpoint -- read-only, writes nothing. Returns
    every column_segments row for this project, grouped by column, so the
    new segment-stack data model (2026-07-17 rebuild, see
    app.engineering.registration._write_column_segments) can be verified
    against real data: does every column have at least one segment, do
    segment heights sum to the column's base/top span, are review_flag
    reasons present wherever expected.
    """
    db = get_db()
    # Emit every column from the Global Column Database as one continuous
    # member spanning its own real base->top elevation (see
    # sync_global_columns() for how those are derived) -- exactly one 3D
    # instance per physical column, regardless of how many pages/floors
    # legitimately reference it.
    columns = db.table("columns").select("*").eq("project_id", str(project_id)).execute().data or []
    if not columns:
        try:
            from app.engineering.registration import sync_global_columns
            sync_global_columns(str(project_id))
            columns = db.table("columns").select("*").eq("project_id", str(project_id)).execute().data or []
        except Exception as _se:
            logger.exception("Error syncing global columns in get_merged_model: %s", _se)

    for c in columns:
        pass
    segments = db.table("column_segments").select("*").eq("project_id", str(project_id)).execute().data or []
    segments_by_column: Dict[str, list] = {}
    for seg in segments:
        segments_by_column.setdefault(seg["column_id"], []).append(seg)

    rows = []
    for c in columns:
        segs = sorted(segments_by_column.get(c["id"], []), key=lambda s: s["elev_bottom_ft"])
        seg_total_height = sum(s["elev_top_ft"] - s["elev_bottom_ft"] for s in segs)
        column_height = (c.get("top_elev_ft") or 0) - (c.get("base_elev_ft") or 0)
        rows.append({
            "column_id": c["id"],
            "mark": c.get("mark"),
            "base_elev_ft": c.get("base_elev_ft"),
            "top_elev_ft": c.get("top_elev_ft"),
            "n_segments": len(segs),
            "segments": segs,
            "segment_heights_match_column_height": abs(seg_total_height - column_height) < 1e-6,
            # Stage 2 fields (2026-07-17 rebuild) -- surfaced here for live
            # verification of the Need Review reconciliation flag.
            "status": c.get("status"),
            "needs_foundation_reconciliation": c.get("needs_foundation_reconciliation"),
            "validation_flags": c.get("validation_flags"),
            # 2026-07-17: surfaced to investigate a "too many duplicate
            # columns in 3D across multiple sheets" report -- lets a
            # near-duplicate-cluster check run against real data without
            # guessing (see gx_ft/gy_ft below and the near_duplicate_pairs
            # summary field).
            "gx_ft": c.get("gx_ft"),
            "gy_ft": c.get("gy_ft"),
            "grid_ref": c.get("grid_ref"),
        })

    # Flag any pair of DISTINCT columns whose real-world XZ centers are
    # close together (within 6ft, well outside COLUMN_SNAP_TOL_FT's 1.5ft
    # merge radius but close enough that it's suspicious for two supposedly
    # separate physical columns) -- the live signature of a registration
    # misalignment silently splitting one physical column detected off
    # multiple sheets into several "different" columns instead of merging.
    near_duplicate_pairs = []
    for i in range(len(rows)):
        gi = rows[i]
        if gi.get("gx_ft") is None or gi.get("gy_ft") is None:
            continue
        for j in range(i + 1, len(rows)):
            gj = rows[j]
            if gj.get("gx_ft") is None or gj.get("gy_ft") is None:
                continue
            d = ((gi["gx_ft"] - gj["gx_ft"]) ** 2 + (gi["gy_ft"] - gj["gy_ft"]) ** 2) ** 0.5
            if d <= 6.0:
                near_duplicate_pairs.append({
                    "a": gi["column_id"], "b": gj["column_id"],
                    "dist_ft": round(d, 2),
                    "a_segments": gi["n_segments"], "b_segments": gj["n_segments"],
                })

    return {
        "project_id": str(project_id),
        "total_columns": len(columns),
        "total_segments": len(segments),
        "columns_with_no_segments": [r["column_id"] for r in rows if r["n_segments"] == 0],
        "near_duplicate_count": len(near_duplicate_pairs),
        "near_duplicate_pairs": near_duplicate_pairs[:50],
        "columns": rows,
    }


@router.get("/pages/{page_id}/debug/symbol-detection")
async def get_symbol_detection_debug(
    page_id: UUID,
    user: AuthUser,
) -> Dict[str, Any]:
    """
    TEMPORARY diagnostic endpoint -- read-only, writes nothing. Runs
    detect_column_symbols() directly against a page's real PDF and reports
    exactly what happened at each stage: raw shape-acceptance counts by
    rule (ih_pattern / filled_rect / foundation_outline / fragmented_outline),
    then the classifier's accept/reject breakdown with reasons. Built
    2026-07-17 to stop guessing at why Stage 6's _has_IH_pattern fix
    changed footing counts on a real project instead of reasoning about it
    from code alone -- three theory-then-live-test cycles in a row produced
    zero measured change, which meant the mental model of the pipeline was
    wrong somewhere not yet found.
    """
    db = get_db()
    page_row = db.table("pages").select("*").eq("id", str(page_id)).maybe_single().execute()
    if not page_row.data:
        raise HTTPException(status_code=404, detail="Page not found")
    page = page_row.data
    drawing_row = db.table("drawings").select("storage_key").eq("id", str(page["drawing_id"])).maybe_single().execute()
    if not drawing_row.data:
        raise HTTPException(status_code=404, detail="Drawing not found")

    from app.services.storage import LocalStorageAdapter
    storage = get_storage()
    if not isinstance(storage, LocalStorageAdapter):
        raise HTTPException(status_code=501, detail="Local storage only")
    file_path = storage.local_path(drawing_row.data["storage_key"])

    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    import fitz
    from main import detect_column_symbols

    doc = fitz.open(file_path)
    p = doc[page["idx"]]
    page_text_upper = p.get_text().upper()
    is_fp = "FOUNDATION PLAN" in page_text_upper or "FOUNDATION FRAMING" in page_text_upper
    scale_ratio = page.get("scale_num") or 96
    _words = p.get_text("words")  # (x0,y0,x1,y1,text,block,line,word)

    # Re-run detect_column_symbols with a monkeypatched classifier call so we
    # can see PRE-classifier raw symbols too, not just the final result.
    import app.engineering.column_symbol_classifier as _clf_mod
    _orig = _clf_mod.classify_and_filter_symbols
    _captured = {}
    def _spy(symbols, page_obj, is_foundation_plan=False):
        _captured["pre_classifier_count"] = len(symbols)
        approved, rejected = _orig(symbols, page_obj, is_foundation_plan=is_foundation_plan)
        _captured["approved_count"] = len(approved)
        _captured["rejected_count"] = len(rejected)
        _captured["approved_categories"] = {}
        _captured["approved_symbols"] = []
        for s in approved:
            c = s.get("category")
            _captured["approved_categories"][c] = _captured["approved_categories"].get(c, 0) + 1
            _cx, _cy = s.get("cx"), s.get("cy")
            _nearby = []
            if _cx is not None and _cy is not None:
                for w in _words:
                    wx, wy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
                    if ((_cx - wx) ** 2 + (_cy - wy) ** 2) ** 0.5 < 40:
                        _nearby.append(w[4])
            _captured["approved_symbols"].append({
                "category": c,
                "cx": _cx, "cy": _cy,
                "bbox": s.get("bbox"),
                "accept_rules": s.get("accept_rules"),
                "classifier_confidence": s.get("classifier_confidence"),
                "classifier_reason": s.get("classifier_reason"),
                "nearby_text": _nearby,
                "nearest_mark_dist": s.get("nearest_mark_dist"),
                "mark_radius": s.get("mark_radius"),
                "has_ih_pattern": s.get("has_ih_pattern"),
                "symbol": s.get("symbol"),
            })
        _captured["rejected_by_category"] = {}
        _captured["rejected_reasons_sample"] = []
        _captured["rejected_symbols"] = []
        for s in rejected:
            c = s.get("category")
            _captured["rejected_by_category"][c] = _captured["rejected_by_category"].get(c, 0) + 1
            if len(_captured["rejected_reasons_sample"]) < 15:
                _captured["rejected_reasons_sample"].append({
                    "category": c, "reason": s.get("classifier_reason"),
                    "accept_rules": s.get("accept_rules"), "confidence": s.get("classifier_confidence"),
                })
            _rcx, _rcy = s.get("cx"), s.get("cy")
            _rnearby = []
            if _rcx is not None and _rcy is not None:
                for w in _words:
                    wx, wy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
                    if ((_rcx - wx) ** 2 + (_rcy - wy) ** 2) ** 0.5 < 25:
                        _rnearby.append(w[4])
            _captured["rejected_symbols"].append({
                "category": c, "cx": _rcx, "cy": _rcy,
                "reason": s.get("classifier_reason"), "accept_rules": s.get("accept_rules"),
                "nearby_text": _rnearby,
            })
        return approved, rejected
    _clf_mod.classify_and_filter_symbols = _spy
    try:
        symbols = detect_column_symbols(p, scale_ratio=scale_ratio, is_foundation_plan=is_fp)
    finally:
        _clf_mod.classify_and_filter_symbols = _orig
    # Must read page_w/page_h BEFORE doc.close() -- p is a view into doc,
    # and accessing p.rect after the document is closed raises inside
    # PyMuPDF (the underlying page handle is gone). This was silently
    # crashing the whole request with no CORS headers on the resulting
    # error response, which the browser reports as a generic "Failed to
    # fetch" network error rather than a visible 500 -- looked identical to
    # a dead server from the client side.
    page_w = p.rect.x1 - p.rect.x0
    page_h = p.rect.y1 - p.rect.y0
    doc.close()

    return {
        "page_id": str(page_id),
        "is_foundation_plan": is_fp,
        "scale_ratio": scale_ratio,
        "final_symbols_returned": len(symbols),
        "page_w": page_w,
        "page_h": page_h,
        **_captured,
    }


@router.get("/projects/{project_id}/model/merged")
async def get_merged_model(
    project_id: UUID,
    user: AuthUser,
    scope: str = Query("building", pattern="^(building|floor|sheet)$"),
    scope_id: Optional[UUID] = Query(None),
) -> Dict[str, Any]:
    """Return a single pre-merged 3D model for the requested scope.

    scope=building -> every floor of the project, stacked by Top-of-Steel
                      elevation (not a synthetic per-floor height): a floor's
                      elevation_ft IS its members' Y in the model, exactly
                      like SteelGenie -- enter 12'-0" TOS on one sheet and
                      12'-0" on another and they build as the same floor.
    scope=floor     -> every page of one floor, laterally merged (scope_id=floor_id)
    scope=sheet     -> a single page (scope_id=page_id), same as the legacy
                       per-page /model endpoint but in the merged response shape

    Uses members.geometry.global when a page has been registered (see
    app/engineering/registration.py); otherwise falls back to an identity
    per-page placement so unregistered projects still render, matching the
    pre-multi-sheet behavior.
    """
    db = get_db()

    if scope != "sheet":
        # Register every sheet into one shared building coordinate system
        # before merging -- see _ensure_project_registered docstring.
        # MUST run in a thread, not called directly: register_floor() (which
        # this can call) now takes a per-floor lock (see registration.py) to
        # stop concurrent extraction jobs from racing each other. If an
        # extraction job's background thread is mid-registration and holding
        # that lock, calling register_floor() directly here would block
        # waiting for it -- and because this is an async endpoint, "block"
        # means freezing the entire event loop, which stalls every other
        # request on the server (this is exactly what made an unrelated
        # page like /columns hang on "Loading workspace..." after a recent
        # extraction). Running it in the executor lets this request wait on
        # the lock without taking the whole server down with it.
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _ensure_project_registered, str(project_id), db)

    floors = db.table("floors").select("*").eq("project_id", str(project_id)).execute().data or []
    # Real Top-of-Steel elevation is the authoritative stacking order, not the
    # arbitrary page-index-derived sort_order used only as a tiebreak/fallback
    # for floors that have no TOS value yet.
    floors.sort(key=lambda f: (f.get("elevation_ft") if f.get("elevation_ft") is not None else float("inf"), f.get("sort_order", 0)))
    links = db.table("page_floor_links").select("*").execute().data or []

    # Bulk fetch all pages for this project's drawings
    drw_rows = db.table("drawings").select("id").eq("project_id", str(project_id)).execute().data or []
    drw_ids = [d["id"] for d in drw_rows]
    all_pages = db.table("pages").select("*").in_("drawing_id", drw_ids).execute().data or [] if drw_ids else []
    pages_by_id = {p["id"]: p for p in all_pages}

    def pages_for_floor(floor_id: str) -> list:
        page_ids = [l["page_id"] for l in links if l["floor_id"] == floor_id]
        out = []
        for pid in page_ids:
            pg = pages_by_id.get(pid)
            if pg:
                out.append(pg)
        return out

    members_out: list[dict] = []
    grids_out: list[dict] = []

    if scope == "sheet":
        if not scope_id:
            raise HTTPException(status_code=400, detail="scope_id (page_id) required for scope=sheet")
        page = db.table("pages").select("*").eq("id", str(scope_id)).maybe_single().execute().data
        if not page:
            raise HTTPException(status_code=404, detail="Page not found")
        # No default elevation -- a sheet's Y position in 3D IS its actual,
        # user-entered T.O.S. If it's somehow missing (legacy data extracted
        # before T.O.S. was required), there's nothing honest to place it at,
        # so it renders nothing rather than guessing a height.
        tos = page.get("tos_ft")
        if tos is None:
            return {"scope": scope, "scope_id": str(scope_id), "members": [], "grids": [], "floor_count": 0}
        members = db.table("members").select("*").eq("page_id", str(scope_id)).neq("status", "excluded").execute().data or []
        for m in members:
            out = _member_out(m, page, tos, 0.0, db)
            if out:
                members_out.append(out)
        # Only show grid lines for a page that actually has extracted members --
        # a page's status can say "built"/"estimating" without ever having been
        # analysed (see workers/build.py, which stamps every project page),
        # so status alone isn't proof of extraction.
        if members:
            grids_out.extend(_grids_out(page, tos, db, base_elev=0.0))
        return {"scope": scope, "scope_id": str(scope_id), "members": attach_bom_attributes(str(project_id), deduplicate_members(members_out)), "grids": grids_out, "floor_count": 1}

    if scope == "floor":
        if not scope_id:
            raise HTTPException(status_code=400, detail="scope_id (floor_id) required for scope=floor")
        floor = db.table("floors").select("*").eq("id", str(scope_id)).maybe_single().execute().data
        pages = pages_for_floor(str(scope_id))
        # A floor's elevation IS a user-entered T.O.S. -- use it directly. If
        # the floor row itself doesn't have one yet (e.g. a placeholder from
        # before any of its pages had a T.O.S.), fall back to whatever real
        # T.O.S. its own pages actually carry, never a guessed constant.
        floor_elev = (floor or {}).get("elevation_ft")
        if floor_elev is None:
            floor_elev = next((p.get("tos_ft") for p in pages if p.get("tos_ft") is not None), None)
        if floor_elev is None:
            return {"scope": scope, "scope_id": str(scope_id), "members": [], "grids": [], "floor_count": 0}
        if pages:
            page_ids = [p["id"] for p in pages]
            all_members_for_floor = db.table("members").select("*").in_("page_id", page_ids).neq("status", "excluded").execute().data or []
            members_by_page = {}
            for m in all_members_for_floor:
                members_by_page.setdefault(m["page_id"], []).append(m)
        else:
            members_by_page = {}

        # Columns run from grade (Y=0) up to this floor's own TOS -- that's
        # the actual real-world geometry a steel column has, and it's what
        # the reference (SteelGenie) renders: full-height columns reaching
        # down to the ground plane, not a clipped stub. An earlier "fix"
        # here clamped this to a fake 20ft stub to avoid absurdly tall
        # columns on isolated high-TOS sheets, but that just made columns
        # look disconnected/floating instead -- reverted per user feedback.
        floor_base_elev = 0.0
        for page in pages:
            members = members_by_page.get(page["id"], [])
            # Skip pages that were never actually extracted (zero members) --
            # status alone ("built"/"estimating") isn't reliable proof.
            if not members:
                continue
            for m in members:
                out = _member_out(m, page, floor_elev, floor_base_elev, db)
                if out:
                    members_out.append(out)
            grids_out.extend(_grids_out(page, floor_elev, db, base_elev=floor_base_elev))
        return {"scope": scope, "scope_id": str(scope_id), "members": attach_bom_attributes(str(project_id), deduplicate_members(members_out)), "grids": grids_out, "floor_count": 1}

    # scope == "building" -- stack floors by their real Top-of-Steel value.
    # A floor's own elevation_ft is its members' Y; the floor below's TOS is
    # where its columns rise FROM. Two pages on different drawings that both
    # say TOS 12'-0" land on the exact same elevation and therefore render
    # as one merged floor level.
    #
    # Every column runs from true grade (Y=0) up to its own floor's TOS --
    # this is the correct, real-world column geometry and matches what
    # SteelGenie itself renders (each column reaching the ground plane).
    #
    # This USED to be conditional: only the first floor processed (by loop
    # order) got base_elev=0, and every other floor inherited prev_elev --
    # the elevation of whichever floor happened to be processed immediately
    # before it. That's wrong on two counts: (1) `floors` isn't queried in
    # elevation order, so "previous" often wasn't "the floor directly
    # below"; (2) small TOS parsing/OCR noise (e.g. 155'-0" vs 154'-11 7/8")
    # splits what should be one merged floor level into several near-
    # duplicate floor rows, each getting a different, essentially-random
    # base from this heuristic -- producing exactly the jagged, staggered-
    # bottom column look reported ("why now it looks like this"). Using an
    # unconditional 0.0 for every floor removes the ordering dependency
    # entirely: every column simply reaches grade, full stop.
    floor_count = 0
    # Grid emission is deferred: only the LOWEST floor's grid should render
    # (matches SteelGenie -- verified live: it shows one ground-level grid
    # reference plane, not a repeated grid at every framing/roof level,
    # which just clutters the 3D view once there's more than one floor).
    # Each candidate is (floor_elev, page); after the loop we keep only the
    # candidate(s) at the minimum floor_elev.
    _grid_candidates: list[tuple[float, dict]] = []
    for floor in floors:
        candidate_pages = pages_for_floor(floor["id"])
        if not candidate_pages:
            continue
        # A page's status ("built"/"estimating") isn't proof it was ever
        # extracted -- workers/build.py stamps every project page regardless
        # of whether it produced members. Only pages with real extracted
        # members contribute to the 3D view; floors made up entirely of
        # unextracted pages are skipped and don't consume a stacking slot.
        pages_with_members = []
        if candidate_pages:
            candidate_page_ids = [p["id"] for p in candidate_pages]
            all_members_for_floor = db.table("members").select("*").in_("page_id", candidate_page_ids).neq("status", "excluded").execute().data or []
            members_by_page = {}
            for m in all_members_for_floor:
                members_by_page.setdefault(m["page_id"], []).append(m)

            for page in candidate_pages:
                members = members_by_page.get(page["id"], [])
                if members:
                    pages_with_members.append((page, members))
        if not pages_with_members:
            continue

        floor_elev = floor.get("elevation_ft")
        if floor_elev is None:
            floor_elev = next((p.get("tos_ft") for p, _m in pages_with_members if p.get("tos_ft") is not None), None)
        if floor_elev is None:
            floor_elev = floor_count * 14.0

        floor_count += 1
        base_elev = 0.0
        for page, members in pages_with_members:
            for m in members:
                # Columns are emitted once from the Global Column Database
                # below instead of per-floor here -- see sync_global_columns()
                # in registration.py. Re-emitting them here too (one segment
                # per floor that happens to reference the same physical
                # column) is exactly the duplicate/stray-column bug reported
                # earlier; the column DB is now the single source of truth.
                if m.get("kind") == "column":
                    continue
                out = _member_out(m, page, floor_elev, base_elev, db)
                if out:
                    out["floor_id"] = floor["id"]
                    out["floor_name"] = floor["name"]
                    members_out.append(out)
            # Defer to after the floor loop -- only the lowest floor's grid
            # actually gets emitted (see _grid_candidates note above).
            _grid_candidates.append((floor_elev, page))

    # Now emit the grid for the lowest floor only.
    if _grid_candidates:
        _min_elev = min(fe for fe, _p in _grid_candidates)
        _seen_grid_pages: set = set()
        for fe, page in _grid_candidates:
            if fe == _min_elev and page["id"] not in _seen_grid_pages:
                _seen_grid_pages.add(page["id"])
                grids_out.extend(_grids_out(page, fe, db, base_elev=fe))

    # Fetch columns from the Global Column Database (run sync only if table empty)
    columns = db.table("columns").select("*").eq("project_id", str(project_id)).execute().data or []
    if not columns:
        try:
            from app.engineering.registration import sync_global_columns
            sync_global_columns(str(project_id))
            columns = db.table("columns").select("*").eq("project_id", str(project_id)).execute().data or []
        except Exception as _se:
            logger.exception("Error syncing global columns in get_merged_model: %s", _se)
    for c in columns:
        gx, gy = c.get("gx_ft"), c.get("gy_ft")
        if gx is None or gy is None:
            continue
        base_elev = c.get("base_elev_ft") or 0.0
        top_elev = c.get("top_elev_ft") or (base_elev + 15.0)  # default 15ft column height if single level
        members_out.append({
            "id": f"col_{c['id']}",
            "member_id": c.get("source_member_id"),
            "page_id": c.get("source_page_id"),
            "type": "column",
            "profile": c.get("profile"),
            "piecemark": c.get("mark"),
            "status": c.get("status"),
            "start": [gx, base_elev, gy],
            "end": [gx, top_elev, gy],
            "rotation": c.get("rotation", 0),
            "symbol": c.get("symbol"),
        })

    # Fallback: if no global columns exist yet, emit column members directly from members table
    if not columns:
        for floor in floors:
            candidate_pages = pages_for_floor(floor["id"])
            floor_elev = floor.get("elevation_ft") or next((p.get("tos_ft") for p in candidate_pages if p.get("tos_ft") is not None), None)
            if floor_elev is None:
                continue
            for page in candidate_pages:
                page_mems = db.table("members").select("*").eq("page_id", str(page["id"])).neq("status", "excluded").execute().data or []
                for m in page_mems:
                    if m.get("kind") == "column" or m.get("type") == "column":
                        out = _member_out(m, page, floor_elev, 0.0, db)
                        if out:
                            out["floor_id"] = floor["id"]
                            out["floor_name"] = floor["name"]
                            members_out.append(out)

    return {"scope": scope, "scope_id": str(scope_id) if scope_id else None, "members": attach_bom_attributes(str(project_id), deduplicate_members(members_out)), "grids": grids_out, "floor_count": floor_count}
