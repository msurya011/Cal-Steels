"""Pydantic v2 schemas for projects."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    number: Optional[str] = None
    status: str = "in_progress"
    design_standard: str = "AISC"
    unit_system: str = "imperial"
    location: Optional[str] = None
    description: Optional[str] = None
    folder_id: Optional[UUID] = None


class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class FolderOut(BaseModel):
    id: UUID
    owner_id: UUID
    company_id: Optional[UUID] = None
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    number: Optional[str] = None
    status: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    pinned: Optional[bool] = None
    folder_id: Optional[UUID] = None


class ProjectOut(BaseModel):
    id: UUID
    owner_id: UUID
    company_id: Optional[UUID] = None
    folder_id: Optional[UUID] = None
    name: str
    number: Optional[str] = None
    status: str
    design_standard: str
    unit_system: str
    location: Optional[str] = None
    description: Optional[str] = None
    pinned: bool = False
    share_scope: str = "private"
    is_example: bool = False
    thumbnail_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListOut(BaseModel):
    items: list[ProjectOut]
    total: int
    has_more: bool
