"""
Ingest worker — processes an uploaded PDF:
1. Splits pages → saves each as an image (thumbnail + full)
2. Creates page records in Supabase
3. Updates drawing status to 'ready'
4. Broadcasts WebSocket progress events
"""
from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any, Dict, Optional

import fitz  # PyMuPDF

from app.core.config import get_settings
from app.core.events import manager as ws_manager
from app.services.database import get_db
from app.services.storage import generate_storage_key, get_storage
from app.workers.queue import _update_job

logger = logging.getLogger(__name__)

_THUMB_DPI = 72     # low-res thumbnail
_PREVIEW_DPI = 150  # medium-res page preview (replaces base64 in page.tsx)


async def run_ingest(
    *,
    job_id: str,
    user_id: str,
    drawing_id: str,
    file_path: str,          # local filesystem path to the uploaded PDF
    project_id: str,
) -> None:
    """
    Ingest worker coroutine.
    Called by workers/queue.py dispatch_job.
    """
    db = get_db()
    storage = get_storage()
    cfg = get_settings()

    async def progress(pct: int, msg: str) -> None:
        await _update_job(job_id, "running", pct, msg)
        await ws_manager.broadcast_job_progress(user_id, job_id, pct, msg)

    await progress(5, "Opening PDF…")

    try:
        doc = fitz.open(file_path)
        page_count = doc.page_count

        # Update drawing with page count
        db.table("drawings").update({
            "page_count": page_count,
            "status": "ingesting",
        }).eq("id", drawing_id).execute()

        pages_to_insert: list[dict] = []

        for idx in range(page_count):
            pct = 10 + int((idx / page_count) * 80)
            await progress(pct, f"Processing page {idx + 1}/{page_count}…")

            page = doc[idx]

            # Render thumbnail (72 dpi)
            thumb_mat = fitz.Matrix(_THUMB_DPI / 72, _THUMB_DPI / 72)
            thumb_pix = page.get_pixmap(matrix=thumb_mat, alpha=False)
            thumb_bytes = thumb_pix.tobytes("jpeg")
            thumb_key = generate_storage_key(f"drawings/{drawing_id}/thumbs", ".jpg")
            await storage.put(thumb_key, thumb_bytes, "image/jpeg")

            # Render preview (150 dpi)
            prev_mat = fitz.Matrix(_PREVIEW_DPI / 72, _PREVIEW_DPI / 72)
            prev_pix = page.get_pixmap(matrix=prev_mat, alpha=False)
            prev_bytes = prev_pix.tobytes("jpeg")
            image_key = generate_storage_key(f"drawings/{drawing_id}/pages", ".jpg")
            await storage.put(image_key, prev_bytes, "image/jpeg")

            # Collect page record — all pages are batch-inserted after the loop
            # so local_db.json is written once instead of once per page.
            pages_to_insert.append({
                "drawing_id": drawing_id,
                "idx": idx,
                "thumb_key": thumb_key,
                "image_key": image_key,
                "status": "not_started",
            })

        # Single batch insert → one DB write for all pages (was N writes)
        batch_resp = db.table("pages").insert(pages_to_insert).execute()
        pages_created = [p["id"] for p in batch_resp.data]

        doc.close()

        # Mark drawing as ready
        db.table("drawings").update({
            "status": "ready",
            "page_count": page_count,
        }).eq("id", drawing_id).execute()

        await _update_job(
            job_id, "done", 100,
            message=f"Ingested {page_count} pages",
            result={"page_count": page_count, "page_ids": pages_created},
            finished=True,
        )
        await ws_manager.broadcast_job_done(
            user_id, job_id,
            result_type="drawing",
            entity_id=drawing_id,
        )
        logger.info("Ingest done: drawing=%s pages=%d", drawing_id, page_count)

    except Exception as exc:
        logger.exception("Ingest failed for drawing %s: %s", drawing_id, exc)
        db.table("drawings").update({"status": "error"}).eq("id", drawing_id).execute()
        raise
