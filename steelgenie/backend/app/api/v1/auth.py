"""
Auth router — /me endpoints.
Supabase handles login/logout; this router handles user profile.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.tenancy import AuthUser
from app.services.database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class UserProfile(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    company_id: Optional[str] = None
    role: str


class UserProfileUpdate(BaseModel):
    name: Optional[str] = None


@router.get("/me", response_model=UserProfile)
async def get_me(user: AuthUser):
    """Return the current user's profile."""
    db = get_db()
    row = db.table("users").select("*").eq("id", user.id).maybe_single().execute()
    if not row or not row.data:
        # Auto-create profile if missing (race with trigger)
        db.table("users").upsert({
            "id": user.id,
            "email": user.email,
        }).execute()
        return UserProfile(id=user.id, email=user.email, role="estimator")
    data = row.data
    return UserProfile(
        id=data["id"],
        email=data["email"],
        name=data.get("name"),
        company_id=data.get("company_id"),
        role=data.get("role", "estimator"),
    )


@router.patch("/me", response_model=UserProfile)
async def update_me(body: UserProfileUpdate, user: AuthUser):
    db = get_db()
    update = body.model_dump(exclude_none=True)
    resp = db.table("users").update(update).eq("id", user.id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")
    data = resp.data[0]
    return UserProfile(
        id=data["id"],
        email=data["email"],
        name=data.get("name"),
        company_id=data.get("company_id"),
        role=data.get("role", "estimator"),
    )
