"""Pydantic v2 schemas for drawings and pages."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class DrawingOut(BaseModel):
    id: UUID
    project_id: UUID
    filename: str
    storage_key: str
    page_count: Optional[int] = None
    file_size: Optional[int] = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PageOut(BaseModel):
    id: UUID
    drawing_id: UUID
    idx: int
    sheet_no: Optional[str] = None
    title: Optional[str] = None
    scale_num: Optional[float] = None
    scale_label: Optional[str] = None
    tos_ft: Optional[float] = None
    status: str
    thumb_url: Optional[str] = None   # signed URL injected server-side
    image_url: Optional[str] = None   # signed URL injected server-side
    # Verified live against the real SteelGenie app (2026-07-17): a
    # foundation-plan sheet labels its elevation field "Bottom of Column",
    # not "Top of Steel" -- surfaced here so the frontend can match that
    # convention. Without this on PageOut, FastAPI's response_model would
    # silently strip the field even though it's stored on the row.
    is_foundation_plan: Optional[bool] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PageUpdate(BaseModel):
    scale_num: Optional[float] = None
    scale_label: Optional[str] = None
    tos_ft: Optional[float] = None
    status: Optional[str] = None
    sheet_no: Optional[str] = None
    title: Optional[str] = None
