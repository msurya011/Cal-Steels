"""
Config router — GET/PUT project engineering configuration.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.tenancy import AuthUser
from app.services.database import get_db

router = APIRouter(tags=["config"])

DEFAULT_CONFIG = {
    "design_method": "ASD",
    "beam_end_reaction": {
        "mode": "udl",
        "udl_percent": 50,
    },
    "seismic": {
        "moment_frame": "non_seismic",
        "brace_frame": "non_seismic",
    },
    "connection_types": {
        "beam_column": "bolted_double_angle",
        "beam_girder": "bolted_double_angle",
        "column_splice_method": "welded_flange",
        "auto_splice": False,
        "max_splice_height_ft": 35.0,
    },
    "materials": {
        "W": "A992",
        "WT": "A992",
        "S": "A36",
        "ST": "A36",
        "C": "A36",
        "L": "A36",
        "M": "A36",
        "MT": "A36",
        "MC": "A36",
        "HP": "A572Gr50",
        "HSS_rect": "A500GrC",
        "HSS_round": "A500GrC",
        "PIPE": "A53GrB",
        "ANCHOR": "Gr36",
        "WELD_STUD": "A108",
        "PLATE": "A50",
        "BOLT": "F3125A325N",
        "ELECTRODE": "E70XX",
    },
    "size_priorities": {
        "shear_tab_thickness": [0.375, 0.5, 0.625, 0.75],
        "double_angle_thickness": [0.25, 0.3125, 0.375, 0.5],
        "bolt_diameters": [0.75, 0.875, 1.0],
    },
    "labor_codes": {
        "enabled": True,
        "length_basis": "face_to_face",
    },
}


class ConfigUpdate(BaseModel):
    payload: Dict[str, Any]
    ai_rationale: Optional[Dict[str, Any]] = None


@router.get("/projects/{project_id}/configuration")
async def get_configuration(project_id: UUID, user: AuthUser) -> Dict[str, Any]:
    db = get_db()
    row = db.table("configurations").select("*").eq("project_id", str(project_id)).maybe_single().execute()
    if not row or not row.data:
        return {"project_id": str(project_id), "payload": DEFAULT_CONFIG, "revision": 0}
    return row.data


@router.put("/projects/{project_id}/configuration")
async def update_configuration(project_id: UUID, body: ConfigUpdate, user: AuthUser) -> Dict[str, Any]:
    db = get_db()
    # Check project access
    p = db.table("projects").select("owner_id").eq("id", str(project_id)).maybe_single().execute()
    if not p or not p.data:
        raise HTTPException(status_code=404, detail="Project not found")
    if p.data["owner_id"] != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    existing = db.table("configurations").select("revision").eq("project_id", str(project_id)).maybe_single().execute()
    revision = (existing.data.get("revision", 0) + 1) if existing and existing.data else 1

    upsert_data = {
        "project_id": str(project_id),
        "payload": body.payload,
        "ai_rationale": body.ai_rationale,
        "revision": revision,
    }
    resp = db.table("configurations").upsert(upsert_data).execute()
    return resp.data[0] if resp.data else upsert_data


@router.post("/projects/{project_id}/configuration/reset")
async def reset_configuration(project_id: UUID, user: AuthUser) -> Dict[str, Any]:
    """Reset configuration to defaults."""
    db = get_db()
    resp = db.table("configurations").upsert({
        "project_id": str(project_id),
        "payload": DEFAULT_CONFIG,
        "ai_rationale": None,
        "revision": 0,
    }).execute()
    return resp.data[0] if resp.data else {"payload": DEFAULT_CONFIG}
