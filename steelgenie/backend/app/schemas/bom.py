"""BOM schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


class BomItemOut(BaseModel):
    id: UUID
    project_id: UUID
    build_id: Optional[UUID] = None
    piecemark: Optional[str] = None
    category: Optional[str] = None
    qty: int = 1
    section_type: Optional[str] = None
    section: Optional[str] = None
    length_in: Optional[float] = None
    grade: Optional[str] = None
    labor_code: Optional[str] = None
    weight_lbs: Optional[float] = None
    # These are all required by the DB in principle, but the engine doesn't
    # populate them yet (no camber/cope/hole-count computation) — defaulting
    # to 0 here instead of leaving them required prevents a ResponseValidation
    # 500 on every /bom fetch as soon as a real build inserts rows.
    camber: float = 0.0
    cope: int = 0
    holes: int = 0
    weld_studs: int = 0
    status: Optional[str] = None
    sequence: Optional[int] = None
    paint: Optional[str] = None
    is_main: bool = True
    custom: Optional[Dict[str, Any]] = None
    sheet: Optional[str] = None
    drawing_id: Optional[UUID] = None
    comment: Optional[str] = None
    dcr_left: Optional[float] = None
    dcr_right: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BomSummary(BaseModel):
    total_items: int
    total_weight_lbs: float
    total_weight_tons: float
    by_category: Dict[str, int]


class ExportRequest(BaseModel):
    format: str   # bom_csv | kiss | epm_xlsx | pdf | ifc
