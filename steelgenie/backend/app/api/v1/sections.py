"""
API router for structural steel section shapes library.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException

from app.core.tenancy import AuthUser
from app.services.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sections", tags=["sections"])


@router.get("")
async def search_sections(
    user: AuthUser,
    q: Optional[str] = Query(None, description="Search keyword"),
    standard: Optional[str] = Query(None, description="AISC | IS808"),
    section_type: Optional[str] = Query(None, description="W | HSS | C | L"),
    limit: int = Query(50, le=200),
):
    """Search the structural steel shapes library."""
    db = get_db()
    
    # Query builder
    query = db.table("sections").select("*")
    
    if q:
        query = query.ilike("designation", f"%{q}%")
    if standard:
        query = query.eq("standard", standard.upper())
    if section_type:
        query = query.eq("section_type", section_type.upper())
        
    query = query.order("designation").limit(limit)
    
    resp = query.execute()
    return resp.data or []


@router.get("/{designation}")
async def get_section(designation: str, user: AuthUser):
    """Get dimensions and weight details of a single section designation."""
    db = get_db()
    
    resp = db.table("sections").select("*").eq("designation", designation.upper()).maybe_single().execute()
    if not resp or not resp.data:
        # Try a starting-with prefix search
        prefix_resp = db.table("sections").select("*").ilike("designation", f"{designation}%").limit(1).execute()
        if prefix_resp.data:
            return prefix_resp.data[0]
        raise HTTPException(status_code=404, detail=f"Structural shape designation '{designation}' not found")
        
    return resp.data
