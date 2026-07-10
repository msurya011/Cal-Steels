"""
Schedulers router — read (and lightly edit) Column Groups and Braced Frames
produced by the last build.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.core.tenancy import AuthUser
from app.schemas.schedulers import BracedFrameOut, ColumnGroupOut
from app.services.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["schedulers"])


@router.get("/projects/{project_id}/column-groups", response_model=List[ColumnGroupOut])
async def list_column_groups(project_id: UUID, user: AuthUser):
    db = get_db()
    resp = db.table("column_groups").select("*").eq("project_id", str(project_id)).execute()
    return resp.data or []


@router.patch("/column-groups/{group_id}", response_model=ColumnGroupOut)
async def update_column_group(group_id: UUID, body: Dict[str, Any], user: AuthUser):
    db = get_db()
    allowed = {k: v for k, v in body.items() if k in ("name", "base_plate", "anchors", "splice")}
    resp = db.table("column_groups").update(allowed).eq("id", str(group_id)).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Column group not found")
    return resp.data[0]


@router.get("/projects/{project_id}/braced-frames", response_model=List[BracedFrameOut])
async def list_braced_frames(project_id: UUID, user: AuthUser):
    db = get_db()
    resp = db.table("braced_frames").select("*").eq("project_id", str(project_id)).execute()
    return resp.data or []


@router.patch("/braced-frames/{frame_id}", response_model=BracedFrameOut)
async def update_braced_frame(frame_id: UUID, body: Dict[str, Any], user: AuthUser):
    db = get_db()
    allowed = {k: v for k, v in body.items() if k in ("name", "frame_type", "connection_method")}
    resp = db.table("braced_frames").update(allowed).eq("id", str(frame_id)).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Braced frame not found")
    return resp.data[0]
