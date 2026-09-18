"""
Floors router — multi-sheet floor clustering, grid inspection, and
page registration into a shared per-floor coordinate system.

See docs/multi-sheet-3d-architecture.md for the design this implements.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from uuid import UUID


from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.tenancy import AuthUser
from app.engineering.registration import (
    cluster_pages_into_floors,
    extract_grids_for_page,
    register_floor,
)
from app.services.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["floors"])


@router.post("/projects/{project_id}/floors/auto-cluster")
async def auto_cluster_floors(project_id: UUID, user: AuthUser):
    """Group all of a project's pages into floors by parsed level name.
    Idempotent: pages already linked to a floor (manual or previous run)
    are left untouched."""
    result = cluster_pages_into_floors(str(project_id))
    return result


@router.get("/projects/{project_id}/floors")
async def list_floors(project_id: UUID, user: AuthUser):
    db = get_db()
    floors = db.table("floors").select("*").eq("project_id", str(project_id)).execute().data or []
    floors.sort(key=lambda f: (f.get("elevation_ft") if f.get("elevation_ft") is not None else float("inf"), f.get("sort_order", 0)))
    links = db.table("page_floor_links").select("*").execute().data or []
    regs = db.table("page_registrations").select("*").execute().data or []
    reg_by_page = {r["page_id"]: r for r in regs}

    out = []
    for f in floors:
        floor_links = [l for l in links if l["floor_id"] == f["id"]]
        pages = []
        for link in floor_links:
            page = db.table("pages").select("*").eq("id", link["page_id"]).maybe_single().execute().data
            if not page:
                continue
            reg = reg_by_page.get(link["page_id"])
            pages.append({
                "page_id": page["id"],
                "idx": page.get("idx"),
                "title": page.get("title"),
                "sheet_no": page.get("sheet_no"),
                "zone_label": link.get("zone_label"),
                "status": page.get("status"),
                "registration": reg,
            })
        pages.sort(key=lambda p: p.get("idx") or 0)
        out.append({**f, "pages": pages})
    return out


@router.post("/floors/{floor_id}/register")
async def register_floor_endpoint(floor_id: UUID, user: AuthUser):
    """Solve and persist each member page's transform into a shared
    floor-global feet coordinate system, then write geometry.global on
    every member of the floor."""
    floor = get_db().table("floors").select("*").eq("id", str(floor_id)).maybe_single().execute().data
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")
    # Run off the event loop -- register_floor() now takes a per-floor lock
    # (see registration.py) so concurrent extraction jobs don't race each
    # other. Calling it directly here would block this whole async endpoint
    # -- and with it, the entire server's event loop -- for as long as it
    # takes to acquire that lock if an extraction job is mid-registration.
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, register_floor, str(floor_id))
    return result


@router.post("/projects/{project_id}/floors/register-all")
async def register_all_floors(project_id: UUID, user: AuthUser, force: bool = Query(False)):
    """Convenience: auto-cluster (if needed) then register every floor of a
    project in one call. Used by the 3D page's "Rebuild Model" action."""
    cluster_result = cluster_pages_into_floors(str(project_id))
    db = get_db()
    floors = db.table("floors").select("*").eq("project_id", str(project_id)).execute().data or []

    # Phase 1 Fix C: Back-fill floors.elevation_ft from their linked pages' tos_ft.
    # Floors created via title-text clustering (before any page had a TOS value)
    # have elevation_ft = null. Once pages are extracted with a real TOS, the
    # floor must pick that value up so the 3D model stacks at the correct Y.
    links = db.table("page_floor_links").select("*").execute().data or []
    page_ids_in_project = list({l["page_id"] for l in links})
    
    # Bulk fetch all relevant pages and registrations for this project
    all_pages = []
    all_regs = []
    if page_ids_in_project:
        all_pages = db.table("pages").select("id, status, tos_ft").in_("id", page_ids_in_project).execute().data or []
        all_regs = db.table("page_registrations").select("page_id, floor_id").in_("page_id", page_ids_in_project).execute().data or []
    
    page_lookup = {p["id"]: p for p in all_pages}
    regs_by_floor = {}
    for r in all_regs:
        regs_by_floor.setdefault(r["floor_id"], set()).add(r["page_id"])
        
    for f in floors:
        if f.get("elevation_ft") is not None:
            continue  # already has an elevation
        floor_page_ids = [l["page_id"] for l in links if l["floor_id"] == f["id"]]
        tos_values = []
        for pid in floor_page_ids:
            pg = page_lookup.get(pid)
            if pg and pg.get("tos_ft") is not None:
                tos_values.append(pg["tos_ft"])
        if tos_values:
            derived_elev = round(sum(tos_values) / len(tos_values), 2)  # median-of-page TOS
            db.table("floors").update({"elevation_ft": derived_elev}).eq("id", f["id"]).execute()
            f["elevation_ft"] = derived_elev  # update local copy so register_floor sees it

    # See register_floor_endpoint above for why this runs off the event
    # loop: register_floor()'s per-floor lock means calling it directly
    # here can block waiting on an in-progress extraction job's
    # registration pass -- and this endpoint is hit on EVERY 3D view load
    # (see StructuralViewer3D's ensureRegistered()), so blocking the event
    # loop here freezes the entire server, not just the 3D pane.
    loop = asyncio.get_event_loop()
    results = []
    for f in floors:
        if not force:
            # A floor needs registration if any of its extracted pages are missing from page_registrations
            floor_page_ids = [l["page_id"] for l in links if l["floor_id"] == f["id"]]
            extracted_page_ids = {pid for pid in floor_page_ids if page_lookup.get(pid, {}).get("status") in ["built", "estimating"]}
            registered_page_ids = regs_by_floor.get(f["id"], set())

            # If the floor has no extracted pages, or all extracted pages are already registered, skip.
            if not extracted_page_ids or extracted_page_ids.issubset(registered_page_ids):
                results.append({"floor_id": f["id"], "name": f["name"], "status": "skipped_already_registered"})
                continue

        reg_result = await loop.run_in_executor(None, register_floor, f["id"])
        results.append({"floor_id": f["id"], "name": f["name"], **reg_result})
    return {"cluster": cluster_result, "floors": results}


@router.get("/pages/{page_id}/grids")
async def get_page_grids(page_id: UUID, user: AuthUser):
    db = get_db()
    return db.table("grids").select("*").eq("page_id", str(page_id)).execute().data or []


_GEOM_CACHE: Dict[Tuple[str, int, Optional[float], float], Dict[str, Any]] = {}


def _get_cached_geom_results(pdf_path: str, page_idx: int, scale_num: float | None) -> Dict[str, Any]:
    from app.engineering.grid_geometry_pass import run_deterministic_geometry_pass
    override_ppf = (864.0 / scale_num) if scale_num and scale_num > 0 else None
    try:
        mtime = os.path.getmtime(pdf_path)
    except Exception:
        mtime = 0.0
    cache_key = (pdf_path, page_idx, override_ppf, mtime)
    if cache_key in _GEOM_CACHE:
        return _GEOM_CACHE[cache_key]
    res = run_deterministic_geometry_pass(
        pdf_path, page_number=page_idx, override_pts_per_foot=override_ppf
    )
    if len(_GEOM_CACHE) > 50:
        _GEOM_CACHE.clear()
    _GEOM_CACHE[cache_key] = res
    return res


def _compute_grid_dimensions(pdf_path: str, page_idx: int, scale_num: float | None) -> list:
    from app.engineering.grid_geometry_pass import to_frontend_dimension_lines
    results = _get_cached_geom_results(pdf_path, page_idx, scale_num)
    return to_frontend_dimension_lines(results)


def _compute_work_point(pdf_path: str, page_idx: int, scale_num: float | None) -> dict | None:
    from app.engineering.grid_geometry_pass import to_frontend_work_point
    results = _get_cached_geom_results(pdf_path, page_idx, scale_num)
    return to_frontend_work_point(results)


@router.get("/pages/{page_id}/grid-dimensions")
async def get_page_grid_dimensions(page_id: UUID, user: AuthUser):
    """Extract and return bay-to-bay grid dimensions with measured scale feet and OCR text."""
    db = get_db()
    page = db.table("pages").select("*").eq("id", str(page_id)).maybe_single().execute().data
    if not page:
        return []

    scale_num = page.get("scale_num")

    drawing = db.table("drawings").select("*").eq("id", page["drawing_id"]).maybe_single().execute().data
    if not drawing:
        return []
    storage_key = drawing.get("storage_key") or drawing.get("file_url")
    if not storage_key:
        return []
    
    from app.services.storage import get_storage
    storage = get_storage()
    pdf_path = storage.local_path(storage_key)
    if not os.path.exists(pdf_path):
        return []
    
    try:
        loop = asyncio.get_event_loop()
        dims = await loop.run_in_executor(
            None, _compute_grid_dimensions, pdf_path, page["idx"], scale_num
        )
        return dims
    except Exception as exc:
        logger.warning("Error calculating grid dimensions for page %s: %s", page_id, exc)
        return []


def _compute_work_point_from_db_grids(db_grids: list) -> dict | None:
    """Compute work point directly from normalized grids stored in DB."""
    if not db_grids:
        return None
    from app.engineering.grid_geometry_pass import to_frontend_work_point
    v_grids = []
    h_grids = []
    for g in db_grids:
        pos = g.get("position")
        if pos is None:
            continue
        try:
            pos_f = float(pos)
        except (ValueError, TypeError):
            continue
        axis = str(g.get("axis", "")).lower()
        lbl = str(g.get("label", "")).strip()
        if axis == "x":
            v_grids.append({"label": lbl, "x": pos_f})
        elif axis == "y":
            h_grids.append({"label": lbl, "y": pos_f})

    if not v_grids or not h_grids:
        return None

    return to_frontend_work_point({
        "vertical_grids": v_grids,
        "horizontal_grids": h_grids,
        "page_dimensions": {"width": 1.0, "height": 1.0},
    })


@router.get("/pages/{page_id}/work-point")
async def get_page_work_point(page_id: UUID, user: AuthUser):
    """Return the plan's implied Work Point (WP) -- the first grid in each
    axis's own label sequence (e.g. grid 1 / grid A) -- as a single
    normalized-coordinate marker for the overlay.
    Attempts extraction from the PDF drawing first, and falls back to
    persisted database grids if the PDF geometry pass is unavailable or returns None.
    Scale calibration is optional (coordinates are normalized 0-1)."""
    db = get_db()
    page = db.table("pages").select("*").eq("id", str(page_id)).maybe_single().execute().data
    if not page:
        return None

    scale_num = page.get("scale_num")
    wp = None

    drawing = db.table("drawings").select("*").eq("id", page["drawing_id"]).maybe_single().execute().data
    if drawing:
        storage_key = drawing.get("storage_key") or drawing.get("file_url")
        if storage_key:
            from app.services.storage import get_storage
            storage = get_storage()
            pdf_path = storage.local_path(storage_key)
            if os.path.exists(pdf_path):
                try:
                    loop = asyncio.get_event_loop()
                    wp = await loop.run_in_executor(
                        None, _compute_work_point, pdf_path, page["idx"], scale_num
                    )
                except Exception as exc:
                    logger.warning("Error calculating work point from PDF for page %s: %s", page_id, exc)

    # Robust fallback: if PDF geometry pass yielded no work point, derive from persisted grids
    if not wp:
        try:
            db_grids = db.table("grids").select("*").eq("page_id", str(page_id)).execute().data or []
            wp = _compute_work_point_from_db_grids(db_grids)
        except Exception as exc:
            logger.warning("Error computing work point from DB grids for page %s: %s", page_id, exc)

    return wp


@router.post("/pages/{page_id}/gemini-takeoff")
async def run_page_gemini_estimator_takeoff(page_id: UUID, user: AuthUser):
    """Run Senior Structural Estimator Gemini AI Takeoff for grid-to-grid bay lengths & stationing."""
    db = get_db()
    page = db.table("pages").select("*").eq("id", str(page_id)).maybe_single().execute().data
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    drawing = db.table("drawings").select("*").eq("id", page["drawing_id"]).maybe_single().execute().data
    storage_key = drawing.get("storage_key") or drawing.get("file_url")
    if not storage_key:
        raise HTTPException(status_code=400, detail="Drawing file not found")
    
    from app.services.storage import get_storage
    storage = get_storage()
    pdf_path = storage.local_path(storage_key)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Local PDF file not found on disk")
        
    try:
        from estimator_gemini_takeoff import run_estimator_takeoff
        out_img = f"estimator_takeoff_{page_id}.png"
        results = run_estimator_takeoff(pdf_path, page_number=page["idx"], output_image=out_img)
        return {
            "status": "SUCCESS",
            "page_id": str(page_id),
            "takeoff": results,
            "preview_image": f"/api/v1/pages/{page_id}/preview"
        }
    except Exception as exc:
        logger.error("Gemini Estimator Takeoff failed for page %s: %s", page_id, exc)
        raise HTTPException(status_code=500, detail=f"Gemini Estimator Takeoff error: {str(exc)}")


@router.post("/pages/{page_id}/grids/extract")
async def extract_page_grids(page_id: UUID, user: AuthUser):
    return extract_grids_for_page(str(page_id))



class FloorAssignment(BaseModel):
    floor_id: UUID
    zone_label: Optional[str] = None


@router.patch("/pages/{page_id}/floor")
async def assign_page_floor(page_id: UUID, body: FloorAssignment, user: AuthUser):
    """Manual override: move a page to a different floor (or correct its
    zone label). Triggers no automatic re-registration -- call
    POST /floors/{floor_id}/register afterwards to recompute transforms."""
    db = get_db()
    page = db.table("pages").select("*").eq("id", str(page_id)).maybe_single().execute().data
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    floor = db.table("floors").select("*").eq("id", str(body.floor_id)).maybe_single().execute().data
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    db.table("page_floor_links").upsert({
        "page_id": str(page_id),
        "floor_id": str(body.floor_id),
        "zone_label": body.zone_label,
    }).execute()
    return {"ok": True}


class RegistrationOverride(BaseModel):
    tx_ft: Optional[float] = None
    ty_ft: Optional[float] = None
    rotation_deg: Optional[float] = None


@router.patch("/pages/{page_id}/registration")
async def override_page_registration(page_id: UUID, body: RegistrationOverride, user: AuthUser):
    """Manual nudge/rotate override for a page's resolved transform.
    Marks method='manual' so future auto re-registration of the floor
    won't silently overwrite the correction."""
    db = get_db()
    reg = db.table("page_registrations").select("*").eq("page_id", str(page_id)).maybe_single().execute().data
    if not reg:
        raise HTTPException(status_code=404, detail="Page has not been registered yet")

    update: dict[str, Any] = {"method": "manual", "confidence": 1.0}
    if body.tx_ft is not None:
        update["tx_ft"] = body.tx_ft
    if body.ty_ft is not None:
        update["ty_ft"] = body.ty_ft
    if body.rotation_deg is not None:
        update["rotation_deg"] = body.rotation_deg

    db.table("page_registrations").update(update).eq("page_id", str(page_id)).execute()

    from app.engineering.registration import write_global_geometry
    write_global_geometry(str(page_id))
    return {"ok": True}
