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
    qty: int
    section_type: Optional[str] = None
    section: Optional[str] = None
    length_in: Optional[float] = None
    grade: Optional[str] = None
    labor_code: Optional[str] = None
    weight_lbs: Optional[float] = None
    camber: float
    cope: int
    holes: int
    weld_studs: int
    status: Optional[str] = None
    sequence: Optional[int] = None
    paint: Optional[str] = None
    is_main: bool
    custom: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BomSummary(BaseModel):
    total_items: int
    total_weight_lbs: float
    total_weight_tons: float
    by_category: Dict[str, int]


class ExportRequest(BaseModel):
    format: str   # bom_csv | kiss | epm_xlsx | pdf | ifc
