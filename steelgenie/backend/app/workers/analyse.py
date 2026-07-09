"""
Analysis worker — wraps the existing CV extraction engine.
Reads the page image from storage, runs extraction, saves members to Supabase.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.core.events import manager as ws_manager
from app.services.database import get_db
from app.services.storage import get_storage
from app.workers.queue import _update_job

logger = logging.getLogger(__name__)


def _run_extraction_sync(
    file_path: str,
    page_index: int,
    scale_ratio: float,
    detect_braces: bool,
    detect_unlabeled: bool,
    ocr_dpi: int,
    floor_elevation_ft: float,
) -> Dict[str, Any]:
    """
    Synchronous wrapper around the existing extraction engine in backend/main.py.
    We import the core extraction logic from the original main.py module to preserve
    all the tested extraction behavior.

    This function runs in a thread pool executor to avoid blocking the event loop.
    """
    # Add backend directory to sys.path so we can import main.py extraction functions
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    try:
        # Import the existing extraction functions from the original main.py
        import importlib
        main_mod = importlib.import_module("main")

        # Build the request the legacy engine expects.
        # NOTE: legacy analyse_pdf does os.path.join(UPLOAD_DIR, req.filename);
        # passing the ABSOLUTE path makes join return the absolute path itself,
        # so the file is found regardless of where the new storage layer put it.
        req = main_mod.AnalysisRequest(
            filename=file_path,
            page_index=page_index,
            scale_ratio=scale_ratio,
            ocr_dpi=ocr_dpi,
            detect_braces=detect_braces,
            detect_unlabeled=detect_unlabeled,
        )

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(main_mod.analyse_pdf(req))
        finally:
            loop.close()
        return result

    except Exception as exc:
        logger.exception("Extraction sync error: %s", exc)
        raise


async def run_analyse(
    *,
    job_id: str,
    user_id: str,
    page_id: str,
    drawing_id: str,
    project_id: str,
    scale_ratio: float,
    detect_braces: bool = True,
    detect_unlabeled: bool = False,
    ocr_dpi: int = 400,
    floor_elevation_ft: float = 12.0,
) -> None:
    """
    Analysis worker coroutine.
    Runs the CV extraction engine and saves members to Supabase.
    """
    db = get_db()
    storage = get_storage()
    cfg = get_settings()

    async def progress(pct: int, msg: str) -> None:
        await _update_job(job_id, "running", pct, msg)
        await ws_manager.broadcast_job_progress(user_id, job_id, pct, msg)

    await progress(5, "Loading page data…")

    # Get page info (no nested join — mock DB doesn't support PostgREST joins)
    page_row = db.table("pages").select("*").eq("id", page_id).single().execute()
    if not page_row.data:
        raise ValueError(f"Page {page_id} not found")

    page_data = page_row.data
    page_idx = page_data["idx"]

    # Get the local path to the PDF file
    from app.services.storage import LocalStorageAdapter
    if isinstance(storage, LocalStorageAdapter):
        # Get original PDF path from drawing storage_key
        drawing_row = db.table("drawings").select("storage_key").eq("id", drawing_id).single().execute()
        if not drawing_row.data:
            raise ValueError(f"Drawing {drawing_id} not found")

        pdf_key = drawing_row.data["storage_key"]
        file_path = storage.local_path(pdf_key)
    else:
        # Download from R2 to a temp file
        import tempfile
        drawing_row = db.table("drawings").select("storage_key").eq("id", drawing_id).single().execute()
        pdf_key = drawing_row.data["storage_key"]
        data = await storage.get(pdf_key)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(data)
            file_path = tmp.name

    await progress(15, "Running member extraction…")

    # Run extraction in thread pool (CPU-bound) while streaming heartbeat progress
    loop = asyncio.get_event_loop()
    t0 = time.time()
    task = loop.run_in_executor(
        None,
        _run_extraction_sync,
        file_path,
        page_idx,
        scale_ratio,
        detect_braces,
        detect_unlabeled,
        ocr_dpi,
        floor_elevation_ft,
    )
    # Heartbeat: advance 15% -> 75% while the engine works so the UI shows life.
    pct = 15
    while not task.done():
        await asyncio.sleep(2)
        if task.done():
            break
        pct = min(75, pct + 2)
        secs = int(time.time() - t0)
        await progress(pct, f"Extracting members… ({secs}s elapsed)")
    result = await task
    elapsed = time.time() - t0

    await progress(80, f"Saving {len(result.get('members', []))} members…")

    # Delete existing members for this page (re-analysis)
    db.table("members").delete().eq("page_id", page_id).execute()

    # Save new members
    raw_members: List[Dict[str, Any]] = result.get("members", [])
    member_rows = []
    for m in raw_members:
        # Map from existing extraction schema to new DB schema
        kind = m.get("type", "beam")
        if kind == "brace":
            kind = "vbrace"
        elif kind not in ("beam", "column", "vbrace", "hbrace", "joist"):
            kind = "beam"

        geometry = {
            "x": m.get("x", 0),
            "y": m.get("y", 0),
            "w": m.get("w", 0),
            "h": m.get("h", 0),
            "bx1": m.get("bx1"),
            "by1": m.get("by1"),
            "bx2": m.get("bx2"),
            "by2": m.get("by2"),
            "angle_deg": m.get("angle_deg"),
            "lx": m.get("lx"),
            "ly": m.get("ly"),
            "sx": m.get("sx"),
            "sy": m.get("sy"),
            "beam_dir": m.get("beam_dir"),
            "color": m.get("color"),
            "unlabeled": m.get("unlabeled", False),
            "overridden": m.get("overridden", False),
        }

        member_rows.append({
            "page_id": page_id,
            "kind": kind,
            "section": m.get("profile"),
            "grade": "A992" if kind in ("beam", "column") else "A36",
            "rotation": m.get("rotation", 0),
            "status": "active",
            "source": "ai",
            "geometry": geometry,
            "confidence": _confidence_to_float(m.get("confidence")),
            "length_ft": m.get("length_ft"),
        })

    # Column cross-validation + missing-column suggestions (Layer 3/4 of the
    # column plan): score detected columns against beam-endpoint support and
    # suggest ghost columns where beams converge with no column detected.
    member_rows = _postprocess_columns(member_rows, page_id)

    if member_rows:
        # Insert in batches of 100
        for i in range(0, len(member_rows), 100):
            db.table("members").insert(member_rows[i:i+100]).execute()

    # Update page status
    db.table("pages").update({"status": "estimating"}).eq("id", page_id).execute()

    summary = result.get("summary", {})
    await _update_job(
        job_id, "done", 100,
        message=f"Extracted {len(member_rows)} members in {elapsed:.1f}s",
        result={
            "member_count": len(member_rows),
            "elapsed": round(elapsed, 2),
            "summary": summary,
        },
        finished=True,
    )
    await ws_manager.broadcast_job_done(
        user_id, job_id,
        result_type="members",
        entity_id=page_id,
    )
    logger.info("Analysis done: page=%s members=%d elapsed=%.1fs", page_id, len(member_rows), elapsed)


def _postprocess_columns(
    member_rows: List[Dict[str, Any]],
    page_id: str,
    endpoint_tol: float = 0.010,      # fraction of page — beam end "supports" a column
    cluster_tol: float = 0.006,       # endpoint clustering grid
    min_converging: int = 3,          # beam ends needed to suggest a missing column
    max_suggestions: int = 30,
) -> List[Dict[str, Any]]:
    """
    Column validation & suggestion pass (pure post-processing; never mutates
    beams). For each detected column, count beam endpoints terminating nearby
    and blend that into confidence/status + error flags. Then, at clusters of
    converging beam endpoints with NO detected column, emit ghost 'suggested'
    columns for the review queue.
    """
    # Gather beam endpoints
    endpoints: List[tuple] = []
    for r in member_rows:
        if r["kind"] != "beam":
            continue
        g = r["geometry"]
        for (px, py) in ((g.get("bx1"), g.get("by1")), (g.get("bx2"), g.get("by2"))):
            if px is not None and py is not None:
                endpoints.append((float(px), float(py)))

    columns = [r for r in member_rows if r["kind"] == "column"]

    # 1) Validate detected columns
    for col in columns:
        g = col["geometry"]
        cx, cy = float(g.get("x", 0)), float(g.get("y", 0))
        support = sum(
            1 for (px, py) in endpoints
            if abs(px - cx) < endpoint_tol and abs(py - cy) < endpoint_tol
        )
        flags: List[str] = []
        conf = col.get("confidence") or 0.5
        if support >= 2:
            conf = min(1.0, conf + 0.15)
        elif support == 0:
            flags.append("orphan")           # no beam frames into this column
            conf = max(0.1, conf - 0.20)
        if not col.get("section"):
            flags.append("no_label")
            conf = max(0.1, conf - 0.10)

        g["beam_support"] = support
        g["error_flags"] = flags
        g["symbol"] = g.get("symbol") or "I"
        col["confidence"] = round(conf, 2)
        if conf < 0.75 or flags:
            col["status"] = "need_review"

    # 2) Suggest missing columns at beam-end convergence points
    if endpoints:
        clusters: Dict[tuple, List[tuple]] = {}
        for (px, py) in endpoints:
            key = (round(px / cluster_tol), round(py / cluster_tol))
            clusters.setdefault(key, []).append((px, py))

        col_pts = [(float(c["geometry"].get("x", 0)), float(c["geometry"].get("y", 0))) for c in columns]
        suggested = 0
        for pts in clusters.values():
            if suggested >= max_suggestions or len(pts) < min_converging:
                continue
            mx = sum(p[0] for p in pts) / len(pts)
            my = sum(p[1] for p in pts) / len(pts)
            near_col = any(abs(mx - qx) < endpoint_tol * 1.5 and abs(my - qy) < endpoint_tol * 1.5
                           for (qx, qy) in col_pts)
            if near_col:
                continue
            member_rows.append({
                "page_id": page_id,
                "kind": "column",
                "section": None,
                "grade": "A992",
                "rotation": 0,
                "status": "need_review",
                "source": "ai",
                "geometry": {
                    "x": round(mx, 4), "y": round(my, 4), "w": 0, "h": 0,
                    "symbol": "I", "suggested": True,
                    "beam_support": len(pts),
                    "error_flags": ["suggested"],
                },
                "confidence": 0.4,
                "length_ft": None,
            })
            suggested += 1
        if suggested:
            logger.info("Column suggestions: %d ghost columns added for page %s", suggested, page_id)

    return member_rows


def _confidence_to_float(conf) -> Optional[float]:
    if conf is None:
        return None
    if isinstance(conf, (int, float)):
        return float(conf)
    if conf == "HIGH":
        return 0.9
    if conf == "MEDIUM":
        return 0.6
    return None
