"""
Notifications router.
"""
from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel
from typing import Optional

from app.core.tenancy import AuthUser
from app.services.database import get_db

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    body: Optional[str] = None
    read_at: Optional[str] = None
    entity: Optional[str] = None
    entity_id: Optional[str] = None
    created_at: str


@router.get("", response_model=List[NotificationOut])
async def list_notifications(user: AuthUser):
    db = get_db()
    resp = db.table("notifications").select("*").eq("user_id", user.id).order("created_at", desc=True).limit(50).execute()
    return resp.data or []


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(notification_id: UUID, user: AuthUser):
    from datetime import datetime, timezone
    db = get_db()
    db.table("notifications").update({
        "read_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", str(notification_id)).eq("user_id", user.id).execute()


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(user: AuthUser):
    from datetime import datetime, timezone
    db = get_db()
    db.table("notifications").update({
        "read_at": datetime.now(timezone.utc).isoformat()
    }).eq("user_id", user.id).is_("read_at", "null").execute()
