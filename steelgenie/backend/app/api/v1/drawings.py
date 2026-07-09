"""
Drawings router — upload PDF, list drawings, get pages.
"""
from __future__ import annotations

import logging
import os
from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, status

from app.core.config import get_settings
from app.core.tenancy import AuthUser
from app.schemas.drawings import DrawingOut, PageOut, PageUpdate
from app.services.database import get_db
from app.services.storage import generate_storage_key, get_storage
from app.workers.ingest import run_ingest
from app.workers.queue import create_job, dispatch_job

logger = logging.getLogger(__name__)
router = APIRouter(tags=["drawings"])

_ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png"}
_ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}


@router.post("/projects/{project_id}/drawings", response_model=DrawingOut, status_code=status.HTTP_201_CREATED)
async def upload_drawing(
    project_id: UUID,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    user: AuthUser,
):
    """Upload a PDF or image and kick off the ingest job."""
    db = get_db()
    cfg = get_settings()
    storage = get_storage()

    # Validate project access
    p = db.table("projects").select("id,owner_id").eq("id", str(project_id)).maybe_single().execute()
    if not p or not p.data:
        raise HTTPException(status_code=404, detail="Project not found")
    if p.data["owner_id"] != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Validate file type
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    # Read and check size
    data = await file.read()
    size_mb = len(data) / (1024 * 1024)
    if size_mb > cfg.max_pdf_size_mb:
        raise HTTPException(status_code=413, detail=f"File too large ({size_mb:.1f} MB > {cfg.max_pdf_size_mb} MB)")

    # Store file with UUID key
    storage_key = generate_storage_key(f"projects/{project_id}/drawings", ext)
    await storage.put(storage_key, data, file.content_type or "application/pdf")

    # Create drawing record
    row = {
        "project_id": str(project_id),
        "filename": file.filename or "upload.pdf",
        "storage_key": storage_key,
        "file_size": len(data),
        "status": "uploaded",
    }
    resp = db.table("drawings").insert(row).execute()
    drawing = resp.data[0]
    drawing_id = drawing["id"]

    # Get local path for the ingest worker
    from app.services.storage import LocalStorageAdapter
    if isinstance(storage, LocalStorageAdapter):
        file_path = storage.local_path(storage_key)
    else:
        # For R2: worker will download it; pass storage_key
        file_path = storage_key

    # Create and dispatch ingest job
    job_id = await create_job("ingest", user.id, str(project_id), drawing_id)
    await dispatch_job(
        background_tasks, job_id, user.id,
        run_ingest,
        drawing_id=drawing_id,
        file_path=file_path,
        project_id=str(project_id),
    )

    return drawing


@router.get("/projects/{project_id}/drawings", response_model=List[DrawingOut])
async def list_drawings(project_id: UUID, user: AuthUser):
    db = get_db()
    resp = db.table("drawings").select("*").eq("project_id", str(project_id)).order("created_at").execute()
    return resp.data or []


@router.get("/drawings/{drawing_id}/pages", response_model=List[PageOut])
async def list_pages(drawing_id: UUID, user: AuthUser):
    db = get_db()
    storage = get_storage()
    resp = db.table("pages").select("*").eq("drawing_id", str(drawing_id)).order("idx").execute()
    pages = resp.data or []

    # Inject signed URLs for thumb and image
    result = []
    for p in pages:
        p = dict(p)
        if p.get("thumb_key"):
            p["thumb_url"] = await storage.signed_url(p["thumb_key"])
        if p.get("image_key"):
            p["image_url"] = await storage.signed_url(p["image_key"])
        result.append(p)
    return result


@router.patch("/pages/{page_id}", response_model=PageOut)
async def update_page(page_id: UUID, body: PageUpdate, user: AuthUser):
    """Update page metadata (scale, TOS, status, sheet number, title)."""
    db = get_db()
    storage = get_storage()
    update = body.model_dump(exclude_none=True)
    resp = db.table("pages").update(update).eq("id", str(page_id)).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Page not found")
    p = dict(resp.data[0])
    if p.get("thumb_key"):
        p["thumb_url"] = await storage.signed_url(p["thumb_key"])
    if p.get("image_key"):
        p["image_url"] = await storage.signed_url(p["image_key"])
    return p


@router.get("/pages/{page_id}", response_model=PageOut)
async def get_page(page_id: UUID, user: AuthUser):
    db = get_db()
    storage = get_storage()
    resp = db.table("pages").select("*").eq("id", str(page_id)).maybe_single().execute()
    if not resp or not resp.data:
        raise HTTPException(status_code=404, detail="Page not found")
    p = dict(resp.data)
    if p.get("thumb_key"):
        p["thumb_url"] = await storage.signed_url(p["thumb_key"])
    if p.get("image_key"):
        p["image_url"] = await storage.signed_url(p["image_key"])
    return p
