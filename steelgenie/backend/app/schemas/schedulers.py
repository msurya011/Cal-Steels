"""Pydantic v2 schemas for the Column and Braced Frame schedulers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


class ColumnGroupOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    column_ids: List[Any] = []
    grids: List[Any] = []
    floors: List[Dict[str, Any]] = []
    splice: Optional[Dict[str, Any]] = None
    base_plate: Optional[Dict[str, Any]] = None
    anchors: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BracedFrameOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    page_id: Optional[UUID] = None
    brace_ids: List[Any] = []
    brace_count: int = 0
    sections: List[Any] = []
    frame_type: Optional[str] = None
    connection_method: Optional[str] = None
    geometry: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BuildTriggerRequest(BaseModel):
    page_ids: Optional[List[UUID]] = None
