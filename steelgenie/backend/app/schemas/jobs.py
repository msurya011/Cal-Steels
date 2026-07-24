"""Pydantic v2 schemas for jobs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel


class JobOut(BaseModel):
    id: UUID
    project_id: Optional[UUID] = None
    drawing_id: Optional[UUID] = None
    page_id: Optional[UUID] = None
    type: str
    status: str
    progress: int
    message: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    engine_version: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalyseRequest(BaseModel):
    scale_ratio: Optional[float] = None
    detect_unlabeled: bool = False
    detect_braces: bool = True
    ocr_dpi: int = 400
    # No default -- Top of Steel varies per drawing and must always be
    # entered by the user for that specific sheet. A caller that omits this
    # gets a 422 instead of silently landing every sheet at the same height.
    floor_elevation_ft: float


class BuildRequest(BaseModel):
    page_ids: Optional[list[UUID]] = None   # None = all pages in project
