"""
Build worker — fetches members + configuration for a project, runs the
engineering engine, and persists bom_items / column_groups / braced_frames.

Mirrors the shape of workers/analyse.py (job progress via _update_job +
WebSocket broadcast) so the frontend job-polling pattern already used for
analysis works unchanged for builds.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from app.core.events import manager as ws_manager
from app.engineering.build import run_build
from app.services.database import get_db
from app.workers.queue import _update_job

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_IMPORT_ERROR = "config_router.DEFAULT_CONFIG"


def _get_default_config() -> Dict[str, Any]:
    # Local import to avoid a circular import (config_router -> ... -> workers).
    from app.api.v1.config_router import DEFAULT_CONFIG
    return DEFAULT_CONFIG


async def run_build_job(
    *,
    job_id: str,
    user_id: str,
    project_id: str,
    page_ids: List[str] | None = None,
) -> None:
    db = get_db()

    async def progress(pct: int, msg: str) -> None:
        await _update_job(job_id, "running", pct, msg)
        await ws_manager.broadcast_job_progress(user_id, job_id, pct, msg)

    await progress(5, "Loading configuration…")
    cfg_row = db.table("configurations").select("payload").eq("project_id", project_id).maybe_single().execute()
    config = (cfg_row.data or {}).get("payload") if cfg_row and cfg_row.data else None
    if not config:
        config = _get_default_config()

    await progress(15, "Loading pages and members…")
    drawings = db.table("drawings").select("*").eq("project_id", project_id).execute()
    drawing_rows = drawings.data or []
    drawing_ids = [d["id"] for d in drawing_rows]
    if not drawing_ids:
        raise ValueError("No drawings found for this project")
    # id -> filename, so BOM rows can be traced back to which uploaded
    # drawing they came from — a project can have multiple drawings, and
    # every drawing's pages restart their idx at 0, so "Page 2" alone is
    # ambiguous across drawings without this.
    drawing_filenames = {d["id"]: d.get("filename") or d["id"] for d in drawing_rows}

    pages: List[Dict[str, Any]] = []
    for did in drawing_ids:
        resp = db.table("pages").select("*").eq("drawing_id", did).execute()
        for p in (resp.data or []):
            p["drawing_id"] = did
            p["drawing_filename"] = drawing_filenames.get(did, did)
            pages.append(p)

    if page_ids:
        page_id_set = set(page_ids)
        pages = [p for p in pages if p["id"] in page_id_set]

    # Order floor-to-floor: ascending Top-of-Steel elevation, falling back to sheet index.
    pages.sort(key=lambda p: (p.get("tos_ft") is None, p.get("tos_ft") or 0, p.get("idx", 0)))

    members_by_page: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    total_members = 0
    for p in pages:
        m_resp = db.table("members").select("*").eq("page_id", p["id"]).neq("status", "excluded").execute()
        members = m_resp.data or []
        members_by_page.append((p, members))
        total_members += len(members)

    if total_members == 0:
        raise ValueError("No members found to build — run Analyse on at least one page first.")

    await progress(40, f"Designing connections for {total_members} members…")
    result = run_build(project_id, config, members_by_page)

    await progress(75, "Saving BOM, column groups, and braced frames…")

    # Replace prior build output for this project (idempotent rebuild).
    db.table("bom_items").delete().eq("project_id", project_id).execute()
    db.table("column_groups").delete().eq("project_id", project_id).execute()
    db.table("braced_frames").delete().eq("project_id", project_id).execute()

    # Batch insert all records to avoid multiple heavy disk writes
    bom_rows = result["bom_items"]
    if bom_rows:
        db.table("bom_items").insert(bom_rows).execute()

    if result["column_groups"]:
        cgroups_to_insert = [{**g, "project_id": project_id} for g in result["column_groups"]]
        db.table("column_groups").insert(cgroups_to_insert).execute()

    if result["braced_frames"]:
        bframes_to_insert = [{**f, "project_id": project_id} for f in result["braced_frames"]]
        db.table("braced_frames").insert(bframes_to_insert).execute()

    # Mark built pages
    if pages:
        pids = [p["id"] for p in pages]
        db.table("pages").update({"status": "built"}).in_("id", pids).execute()

    await _update_job(
        job_id, "done", 100,
        message=f"Build complete — {result['stats']['bom_item_count']} BOM rows, "
                f"{result['stats']['column_group_count']} column groups, "
                f"{result['stats']['braced_frame_count']} braced frames.",
        result={**result["stats"], "engine_version": result["engine_version"], "warnings": result["warnings"]},
        finished=True,
    )
    await ws_manager.broadcast_job_done(user_id, job_id, result_type="build", entity_id=project_id)
    logger.info("Build done: project=%s %s", project_id, result["stats"])
