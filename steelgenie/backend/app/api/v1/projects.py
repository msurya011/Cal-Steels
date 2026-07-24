"""
Projects router — CRUD + clone/share/pin/move.
All endpoints require authentication.
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.core.tenancy import AuthUser
from app.schemas.projects import FolderCreate, FolderOut, ProjectCreate, ProjectOut, ProjectUpdate
from app.services.database import get_db
from app.services.storage import get_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


def _project_or_404(db, project_id: str, user: AuthUser) -> dict:
    """Fetch a project the user can access, or raise 404."""
    row = db.table("projects").select("*").eq("id", project_id).maybe_single().execute()
    if not row or not row.data:
        raise HTTPException(status_code=404, detail="Project not found")
    p = row.data
    # Check ownership or company visibility
    if p["owner_id"] != user.id:
        if p.get("share_scope") != "company" or p.get("company_id") != user.company_id:
            raise HTTPException(status_code=403, detail="Not authorized")
    return p


@router.get("", response_model=List[ProjectOut])
async def list_projects(
    user: AuthUser,
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    folder_id: Optional[UUID] = Query(None),
    pinned: Optional[bool] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List projects the current user owns or can access."""
    db = get_db()
    q = db.table("projects").select("*").or_(
        f"owner_id.eq.{user.id},"
        f"and(share_scope.eq.company,company_id.eq.{user.company_id or '00000000-0000-0000-0000-000000000000'})"
    ).neq("status", "archived").order("updated_at", desc=True)

    if status_filter:
        q = q.eq("status", status_filter)
    if folder_id:
        q = q.eq("folder_id", str(folder_id))
    if pinned is not None:
        q = q.eq("pinned", pinned)
    if search:
        q = q.ilike("name", f"%{search}%")

    q = q.range(offset, offset + limit - 1)
    resp = q.execute()
    projects = resp.data or []

    # The mock DB's or_() is a no-op (see database.py), so in local-dev mode
    # list_projects() above returns every non-archived project regardless of
    # ownership -- the My Projects / Company Projects / Examples tabs on the
    # dashboard rely on the fields below (owner_id, share_scope, is_example)
    # to do that split client-side instead.
    await _attach_thumbnails(db, projects)
    return projects


async def _attach_thumbnails(db, projects: list[dict]) -> None:
    """Best-effort: set thumbnail_url on each project to its first drawing's
    first page thumbnail, so dashboard cards show a real preview instead of
    a generic icon. Skips silently (leaves thumbnail_url unset) for projects
    with no drawings/pages yet."""
    if not projects:
        return
    project_ids = [p["id"] for p in projects]
    drawings = db.table("drawings").select("*").in_("project_id", project_ids).execute().data or []
    if not drawings:
        return
    drawings.sort(key=lambda d: d.get("created_at") or "")
    first_drawing_by_project: dict[str, dict] = {}
    for d in drawings:
        first_drawing_by_project.setdefault(d["project_id"], d)

    drawing_ids = [d["id"] for d in first_drawing_by_project.values()]
    if not drawing_ids:
        return
    pages = db.table("pages").select("*").in_("drawing_id", drawing_ids).execute().data or []
    pages.sort(key=lambda p: p.get("idx", 0))
    first_page_by_drawing: dict[str, dict] = {}
    for p in pages:
        if p.get("thumb_key"):
            first_page_by_drawing.setdefault(p["drawing_id"], p)

    storage = get_storage()
    for proj in projects:
        drawing = first_drawing_by_project.get(proj["id"])
        if not drawing:
            continue
        page = first_page_by_drawing.get(drawing["id"])
        if not page:
            continue
        try:
            proj["thumbnail_url"] = await storage.signed_url(page["thumb_key"])
        except Exception:
            pass


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, user: AuthUser):
    """Create a new project."""
    db = get_db()
    row = {
        "owner_id": user.id,
        "company_id": user.company_id,
        "name": body.name,
        "number": body.number,
        "status": body.status,
        "design_standard": body.design_standard,
        "unit_system": body.unit_system,
        "location": body.location,
        "description": body.description,
        "folder_id": str(body.folder_id) if body.folder_id else None,
        "pinned": False,
        "share_scope": "private",
        "is_example": False,
    }
    resp = db.table("projects").insert(row).execute()
    return resp.data[0]


# ---------------------------------------------------------------------------
# Folders -- registered ahead of /{project_id} so "folders" in the path
# isn't swallowed by the UUID-typed project_id route.
# ---------------------------------------------------------------------------

@router.get("/folders", response_model=List[FolderOut])
async def list_folders(user: AuthUser):
    db = get_db()
    rows = db.table("folders").select("*").execute().data or []
    return [
        f for f in rows
        if f.get("owner_id") == user.id
        or (f.get("company_id") and f.get("company_id") == user.company_id)
    ]


@router.post("/folders", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(body: FolderCreate, user: AuthUser):
    db = get_db()
    row = {"owner_id": user.id, "company_id": user.company_id, "name": body.name}
    resp = db.table("folders").insert(row).execute()
    return resp.data[0]


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(folder_id: UUID, user: AuthUser):
    db = get_db()
    row = db.table("folders").select("*").eq("id", str(folder_id)).maybe_single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Folder not found")
    if row["owner_id"] != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete a folder")
    # Un-file any projects that were in this folder rather than orphaning them.
    projects_in_folder = db.table("projects").select("*").eq("folder_id", str(folder_id)).execute().data or []
    for p in projects_in_folder:
        db.table("projects").update({"folder_id": None}).eq("id", p["id"]).execute()
    db.table("folders").delete().eq("id", str(folder_id)).execute()


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: UUID, user: AuthUser):
    db = get_db()
    return _project_or_404(db, str(project_id), user)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: UUID, body: ProjectUpdate, user: AuthUser):
    db = get_db()
    _project_or_404(db, str(project_id), user)
    update = body.model_dump(exclude_none=True)
    if "folder_id" in update and update["folder_id"] is not None:
        update["folder_id"] = str(update["folder_id"])
    resp = db.table("projects").update(update).eq("id", str(project_id)).execute()
    return resp.data[0]


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID, user: AuthUser):
    db = get_db()
    p = _project_or_404(db, str(project_id), user)
    if p["owner_id"] != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete a project")
    db.table("projects").update({"status": "archived"}).eq("id", str(project_id)).execute()


@router.post("/{project_id}/pin", response_model=ProjectOut)
async def pin_project(project_id: UUID, user: AuthUser):
    db = get_db()
    p = _project_or_404(db, str(project_id), user)
    resp = db.table("projects").update({"pinned": not p.get("pinned", False)}).eq("id", str(project_id)).execute()
    return resp.data[0]


@router.post("/{project_id}/clone", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def clone_project(project_id: UUID, user: AuthUser):
    """Duplicate a project (metadata only; drawings/members are NOT cloned)."""
    db = get_db()
    p = _project_or_404(db, str(project_id), user)
    clone = {
        "owner_id": user.id,
        "company_id": user.company_id,
        "name": f"Copy of {p['name']}",
        "number": p.get("number"),
        "status": "in_progress",
        "design_standard": p.get("design_standard", "AISC"),
        "unit_system": p.get("unit_system", "imperial"),
        "location": p.get("location"),
        "description": p.get("description"),
        "is_example": False,
    }
    resp = db.table("projects").insert(clone).execute()
    return resp.data[0]
