"""Pydantic v2 schemas for members."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


class MemberGeometry(BaseModel):
    x: float
    y: float
    w: float = 0.0
    h: float = 0.0
    bx1: Optional[float] = None
    by1: Optional[float] = None
    bx2: Optional[float] = None
    by2: Optional[float] = None
    angle_deg: Optional[float] = None
    lx: Optional[float] = None
    ly: Optional[float] = None
    sx: Optional[float] = None
    sy: Optional[float] = None


class MemberOut(BaseModel):
    id: UUID
    page_id: UUID
    kind: str
    section: Optional[str] = None
    grade: Optional[str] = None
    rotation: float
    status: str
    source: str
    geometry: Dict[str, Any]
    confidence: Optional[float] = None
    length_ft: Optional[float] = None
    piecemark: Optional[str] = None
    reviewed_by: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemberCreate(BaseModel):
    kind: str = "beam"
    section: Optional[str] = None
    grade: Optional[str] = None
    rotation: float = 0.0
    status: str = "active"
    source: str = "manual"
    geometry: Dict[str, Any] = {}
    length_ft: Optional[float] = None


class MemberUpdate(BaseModel):
    kind: Optional[str] = None
    section: Optional[str] = None
    grade: Optional[str] = None
    rotation: Optional[float] = None
    status: Optional[str] = None
    piecemark: Optional[str] = None
    geometry: Optional[Dict[str, Any]] = None
    length_ft: Optional[float] = None


class MemberBulkUpdate(BaseModel):
    ids: List[UUID]
    update: MemberUpdate


class MemberBulkDelete(BaseModel):
    ids: List[UUID]
