from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from typing import Any, Optional

class LayerPresetBase(BaseModel):
    name: str
    payload: dict

class LayerPresetCreate(LayerPresetBase):
    pass

class LayerPresetOut(LayerPresetBase):
    id: UUID
    user_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True
