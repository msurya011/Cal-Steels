"""
Model router — GET 3D structural model.
Wraps the existing /model endpoint logic from main.py.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict
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
    floor_elevation_ft: float = Query(12.0),
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
