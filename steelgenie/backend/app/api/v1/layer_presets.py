from uuid import UUID
from typing import List
from fastapi import APIRouter, HTTPException, status
from app.core.tenancy import AuthUser
from app.schemas.layer_presets import LayerPresetCreate, LayerPresetOut
from app.services.database import get_db

router = APIRouter(prefix="/projects/{project_id}/layer-presets", tags=["layer_presets"])

@router.get("", response_model=List[LayerPresetOut])
async def list_layer_presets(project_id: UUID, user: AuthUser):
    db = get_db()
    res = db.table("layer_presets").select("*").eq("project_id", str(project_id)).execute()
    return res.data or []

@router.post("", response_model=LayerPresetOut, status_code=status.HTTP_201_CREATED)
async def create_layer_preset(project_id: UUID, body: LayerPresetCreate, user: AuthUser):
    db = get_db()
    row = {
        "project_id": str(project_id),
        "user_id": user.id,
        "name": body.name,
        "payload": body.payload
    }
    res = db.table("layer_presets").insert(row).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to create layer preset")
    return res.data[0]

@router.patch("/{preset_id}", response_model=LayerPresetOut)
async def update_layer_preset(project_id: UUID, preset_id: UUID, body: LayerPresetCreate, user: AuthUser):
    db = get_db()
    existing = db.table("layer_presets").select("*").eq("id", str(preset_id)).eq("project_id", str(project_id)).maybe_single().execute()
    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Layer preset not found")
    
    update = body.model_dump(exclude_none=True)
    res = db.table("layer_presets").update(update).eq("id", str(preset_id)).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to update layer preset")
    return res.data[0]

@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layer_preset(project_id: UUID, preset_id: UUID, user: AuthUser):
    db = get_db()
    existing = db.table("layer_presets").select("*").eq("id", str(preset_id)).eq("project_id", str(project_id)).maybe_single().execute()
    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Layer preset not found")
    
    db.table("layer_presets").delete().eq("id", str(preset_id)).execute()
    return None
