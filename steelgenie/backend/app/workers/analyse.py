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
from typing import Any, Dict, List, Optional, Tuple

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
    # No default -- T.O.S. is per-drawing and always user-entered (see
    # AnalyseRequest.floor_elevation_ft, which is required for the same
    # reason).
    floor_elevation_ft: float,
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

    # Delete existing members, grids, and registrations for this page (re-analysis)
    db.table("members").delete().eq("page_id", page_id).execute()
    db.table("grids").delete().eq("page_id", page_id).execute()
    db.table("page_registrations").delete().eq("page_id", page_id).execute()

    # Save new members
    raw_members: List[Dict[str, Any]] = result.get("members", [])
    member_rows = []
    for m in raw_members:
        # Map from existing extraction schema to new DB schema
        kind = m.get("type", "beam")
        if kind == "brace":
            kind = "vbrace"
        # Stage 3 (2026-07-17 rebuild) added a "footing" member type (see
        # main.py's emit_symbol_columns) so a foundation-plan footing
        # outline and the column that lands on it can be persisted as two
        # linked records instead of one. Before this line, "footing" wasn't
        # in the recognized-kind list below and silently fell through to
        # "beam" -- which is actively dangerous, not just wrong: registration
        # .py's sync_global_columns treats every non-column member's
        # endpoints as beam/joist evidence a column reaches that floor, so a
        # mislabeled footing would have injected fake beam-connectivity
        # evidence at every footing's own position.
        elif kind not in ("beam", "column", "vbrace", "hbrace", "joist", "footing"):
            kind = "beam"

        # Some raw members (e.g. main.py's emit_symbol_columns) already
        # carry their own nested "geometry" dict with extraction-stage-only
        # fields (grid_ref, category, linked_group_id, ...) that the
        # allow-list below doesn't otherwise capture from top-level keys.
        # Read it here so those fields survive into the persisted row
        # instead of being silently discarded on every re-extraction --
        # Stage 3 (2026-07-17 rebuild)'s category/linked_group_id/
        # linked_role are the immediate reason this was added, but
        # grid_ref (referenced by registration.py's B1 grid-corroboration
        # signal) was ALSO being dropped here before this change, for every
        # member, on every project -- a pre-existing gap, not introduced
        # this session, fixed here as a natural side effect of fixing this
        # allow-list for Stage 3.
        _raw_geo = m.get("geometry") or {}
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
            # Propagate the CV engine's confirmation flag so the frontend can
            # visually distinguish ghost/guessed columns (placed wherever beam
            # ends merely converge, profile unknown) from real, confidently
            # matched ones. Previously dropped here, so every ghost column
            # rendered identically to a confirmed one — flooding plans with
            # solid black column squares that were really just low-confidence
            # guesses.
            "suggested": m.get("confirmed") is False,
            "size_unknown": m.get("size_unknown", False),
            "grid_ref": _raw_geo.get("grid_ref"),
            "category": _raw_geo.get("category"),
            "linked_group_id": _raw_geo.get("linked_group_id"),
            "linked_role": _raw_geo.get("linked_role"),
            # Stage 6 Part 2 (2026-07-17): these were ALSO being silently
            # dropped by this allow-list, same bug as grid_ref/category
            # above. raw_x/raw_y (the true detected symbol position, before
            # grid-snapping) and symbol/sym_w/sym_h (the real detected icon
            # type + its actual on-page size) are what the 2D overlay needs
            # to place a marker exactly on the real symbol and draw it at
            # the real symbol's shape/size instead of a generic fixed box --
            # every column/footing on every project was silently losing
            # this data at persistence time, before the frontend ever saw
            # it, which is why the overlay looked "close but not exact."
            "bx1": _raw_geo.get("bx1") if _raw_geo.get("bx1") is not None else m.get("bx1", m.get("x")),
            "by1": _raw_geo.get("by1") if _raw_geo.get("by1") is not None else m.get("by1", m.get("y")),
            "bx2": _raw_geo.get("bx2") if _raw_geo.get("bx2") is not None else m.get("bx2", m.get("x")),
            "by2": _raw_geo.get("by2") if _raw_geo.get("by2") is not None else m.get("by2", m.get("y")),
            "raw_x": _raw_geo.get("raw_x") if (_raw_geo.get("raw_x") is not None and _raw_geo.get("raw_x") != 0) else m.get("x"),
            "raw_y": _raw_geo.get("raw_y") if (_raw_geo.get("raw_y") is not None and _raw_geo.get("raw_y") != 0) else m.get("y"),
            "snap_offset_ft": _raw_geo.get("snap_offset_ft"),
            "symbol": _raw_geo.get("symbol"),
            "sym_w": _raw_geo.get("sym_w"),
            "sym_h": _raw_geo.get("sym_h"),
            "depth_in": _raw_geo.get("depth_in"),
            "error_flags": _raw_geo.get("error_flags"),
            "grid_ref": _raw_geo.get("grid_ref") or m.get("grid_ref"),
            "grid_bay": _raw_geo.get("grid_bay") or m.get("grid_bay"),
            "grid_line": _raw_geo.get("grid_line") or m.get("grid_line"),
            "exact_length_text": _raw_geo.get("exact_length_text") or m.get("exact_length_text"),
        }

        member_rows.append({
            "page_id": page_id,
            "kind": kind,
            "section": m.get("profile"),
            "grade": "A992" if kind in ("beam", "column") else "A36",
            "rotation": m.get("rotation", 0),
            # Preserve the extraction pipeline's own status when it set one
            # (e.g. emit_symbol_columns() marks a low-confidence/no-label
            # symbol-only column "need_review", matching SteelGenie's own
            # "Need Review" flag on guessed columns) -- this used to be
            # unconditionally overwritten to "active" here, silently
            # discarding that distinction before it ever reached the DB.
            "status": m.get("status") or "active",
            "source": "ai",
            "geometry": geometry,
            "confidence": _confidence_to_float(m.get("confidence")),
            "length_ft": m.get("length_ft"),
        })

    # ── Universal Column Cross-Page Reference & Schedule Resolution ────────
    if file_path:
        try:
            from app.engineering.column_reference_resolver import resolve_foundation_plan_columns
            logger.info("Resolving Plan columns & Base Plates against drawing schedule on page idx %d...", page_idx)
            resolve_foundation_plan_columns(file_path, page_idx, member_rows)
        except Exception as res_err:
            logger.warning("Column reference resolution error: %s", res_err)

    is_fp = bool(result.get("is_foundation_plan"))

    # ── Foundation-Anchored Column Propagation ─────────────────────────────
    # NOTE: We no longer query pages by is_foundation_plan (that column does
    # not exist in the DB schema). Foundation propagation is skipped unless
    # the current page itself is detected as a foundation plan.
    if not is_fp and project_id:
        try:
            drw_rows = db.table("drawings").select("id").eq("project_id", str(project_id)).execute().data or []
            drw_ids = [d["id"] for d in drw_rows]
            if drw_ids:
                fp_pages = []  # is_foundation_plan column not in schema; skip cross-page lookup
                if fp_pages:
                    fp_page_ids = [p["id"] for p in fp_pages]
                    fp_members_db = db.table("members").select("*").in_("page_id", fp_page_ids).in_("kind", ["column", "footing"]).execute().data or []
                    if fp_members_db:
                        foundation_cols = []
                        for fpm in fp_members_db:
                            geo = fpm.get("geometry") or {}
                            foundation_cols.append({
                                "x": geo.get("x") if geo.get("x") is not None else fpm.get("x"),
                                "y": geo.get("y") if geo.get("y") is not None else fpm.get("y"),
                                "grid_ref": geo.get("grid_ref"),
                                "symbol": geo.get("symbol", "I"),
                                "profile": fpm.get("section"),
                            })
                        
                        from main import propagate_foundation_columns
                        v_grid = result.get("v_grid") or []
                        h_grid = result.get("h_grid") or []
                        v_labels = result.get("v_labels") or {}
                        h_labels = result.get("h_labels") or {}
                        page_w = result.get("page_w") or 1000.0
                        page_h = result.get("page_h") or 1000.0
                        pts_pf = 72.0 / max(scale_ratio, 1) * 12.0

                        # propagate_foundation_columns() (main.py) decides whether a
                        # foundation column belongs on THIS sheet by checking it
                        # against real framing here -- both its "active framing
                        # envelope" bounding box and its per-column connectivity
                        # radius check walk each member's endpoints (lx/ly, sx/sy,
                        # bx1/by1, bx2/by2), not just one point. Only copying x/y
                        # here collapsed every beam down to its midpoint, which
                        # shrank the envelope to a fraction of the sheet's real
                        # framed area and made columns near a beam's END (not its
                        # middle) fail the connectivity check -- on a real framing
                        # plan this silently rejected almost every real foundation
                        # column, leaving only the handful whose midpoint-only
                        # neighbors happened to still be close enough. Carrying
                        # the full endpoint set through fixes this for any project,
                        # not just one sheet.
                        raw_mem_format = []
                        for mr in member_rows:
                            geo = mr.get("geometry") or {}
                            raw_mem_format.append({
                                "type": mr["kind"],
                                "x": geo.get("x", 0),
                                "y": geo.get("y", 0),
                                "lx": geo.get("lx"),
                                "ly": geo.get("ly"),
                                "sx": geo.get("sx"),
                                "sy": geo.get("sy"),
                                "bx1": geo.get("bx1"),
                                "by1": geo.get("by1"),
                                "bx2": geo.get("bx2"),
                                "by2": geo.get("by2"),
                                "profile": mr.get("section"),
                            })

                        plan_bounds = result.get("plan_bounds")
                        propagated_raw = propagate_foundation_columns(
                            raw_mem_format, foundation_cols,
                            v_grid, h_grid, v_labels, h_labels,
                            page_w, page_h, scale_ratio, pts_pf,
                            plan_bounds=plan_bounds
                        )

                        non_col_rows = [mr for mr in member_rows if mr["kind"] != "column"]
                        new_col_rows = []
                        for pr in propagated_raw:
                            if pr.get("type") == "column":
                                gx = round(pr["x"], 4)
                                gy = round(pr["y"], 4)
                                geo_dict = pr.get("geometry") or {}
                                geo_dict["x"] = gx
                                geo_dict["y"] = gy
                                geo_dict["raw_x"] = gx
                                geo_dict["raw_y"] = gy
                                geo_dict["bx1"] = gx
                                geo_dict["by1"] = gy
                                geo_dict["bx2"] = gx
                                geo_dict["by2"] = gy
                                new_col_rows.append({
                                    "page_id": page_id,
                                    "kind": "column",
                                    "section": pr.get("profile"),
                                    "grade": "A992",
                                    "rotation": 0,
                                    "status": "active",
                                    "source": "ai",
                                    "geometry": geo_dict,
                                    "confidence": 0.9,
                                    "length_ft": None,
                                })
                        member_rows = non_col_rows + new_col_rows
                        logger.info("Propagated %d foundation columns onto page %s", len(new_col_rows), page_id)
        except Exception as exc:
            logger.exception("Error propagating foundation columns in analyse worker: %s", exc)

    # Column cross-validation + missing-column suggestions (Layer 3/4 of the
    # column plan): score detected columns against beam-endpoint support and
    # suggest ghost columns where beams converge with no column detected.
    member_rows = _postprocess_columns(member_rows, page_id, is_foundation_plan=is_fp)

    # Clear old members for this page before inserting fresh extraction results
    try:
        db.table("members").delete().eq("page_id", page_id).execute()
    except Exception as del_exc:
        logger.warning("Failed to clear old members for page %s: %s", page_id, del_exc)

    if member_rows:
        # Insert in batches of 100
        for i in range(0, len(member_rows), 100):
            db.table("members").insert(member_rows[i:i+100]).execute()

    # Persist grid lines with their REAL bubble labels (e.g. "1", "2.3", "A")
    # read straight off this sheet by extract_grid_lines(), instead of the
    # sequential "1,2,3.../A,B,C" placeholder that
    # registration.extract_grids_for_page() falls back to when no grids
    # exist yet. A real label lets the same physical grid line register
    # correctly across multiple sheets of the same floor; a sequential one
    # doesn't, since every page restarts its own numbering from 1/A.
    grid_bubbles = result.get("grid_bubbles") or {}
    grid_rows = []
    for entry in grid_bubbles.get("v", []):
        label = entry.get("label")
        if label is None:
            continue  # no confirmed bubble text -- let the sequential fallback handle it
        grid_rows.append({
            "page_id": page_id, "axis": "x", "label": label,
            "position": entry["position"], "confidence": 0.9, "source": "ai",
        })
    for entry in grid_bubbles.get("h", []):
        label = entry.get("label")
        if label is None:
            continue
        grid_rows.append({
            "page_id": page_id, "axis": "y", "label": label,
            "position": entry["position"], "confidence": 0.9, "source": "ai",
        })
    if grid_rows:
        for i in range(0, len(grid_rows), 100):
            db.table("grids").insert(grid_rows[i:i+100]).execute()
        logger.info("Persisted %d real-labeled grid lines for page=%s", len(grid_rows), page_id)

    # Persist the T.O.S. elevation on the page so that cluster_pages_into_floors()
    # can group this page with other pages at the same elevation into one floor.
    # Without this write, floor clustering has no tos_ft to work from.
    # NOTE: is_foundation_plan is intentionally NOT written here — the column
    # does not exist in the Supabase pages table schema and writing it causes
    # a PGRST204 error that aborts every extraction. The flag is only used
    # locally within this worker via the is_fp variable above.
    page_update = {"status": "estimating"}
    if floor_elevation_ft is not None:
        page_update["tos_ft"] = floor_elevation_ft
    db.table("pages").update(page_update).eq("id", page_id).execute()

    # Register this page's floor NOW, inside the extraction job, instead of
    # leaving it for GET /model/merged's _ensure_project_registered() to do
    # lazily on the next 3D-view fetch. register_floor()'s grid-correlation
    # matching is the slow part of this whole pipeline (confirmed elsewhere
    # to take 45s+ on floors with many grid lines) -- running it inside a
    # synchronous request handler that the 3D viewer's loading-progress bar
    # is waiting on made that bar sit at its asymptotic 95% cap for as long
    # as registration took, looking permanently stuck. Doing it here means
    # it happens once, during the extraction job (which already has its own
    # honest progress bar for exactly this kind of long-running work), so
    # by the time the 3D viewer requests the merged model the page is
    # already registered and that fetch stays fast.
    await progress(90, "Registering sheet into building coordinates…")
    try:
        from app.engineering.registration import cluster_pages_into_floors, register_floor
        await loop.run_in_executor(None, cluster_pages_into_floors, project_id)
        link_row = db.table("page_floor_links").select("floor_id").eq("page_id", page_id).maybe_single().execute()
        floor_id = (link_row.data or {}).get("floor_id") if link_row else None
        if floor_id:
            await loop.run_in_executor(None, register_floor, floor_id)
    except Exception:
        logger.exception("Post-extraction registration failed for page=%s (non-fatal)", page_id)

    summary = result.get("summary", {})
    grid_dimensions = result.get("grid_dimensions", [])
    work_point = result.get("work_point")
    await _update_job(
        job_id, "done", 100,
        message=f"Extracted {len(member_rows)} members in {elapsed:.1f}s",
        result={
            "member_count": len(member_rows),
            "elapsed": round(elapsed, 2),
            "summary": summary,
            "grid_dimensions": grid_dimensions,
            "work_point": work_point,
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
    endpoint_tol: float = 0.03,
    cluster_tol: float = 0.02,
    min_converging: int = 2,
    max_suggestions: int = 20,
    is_foundation_plan: bool = False,
) -> List[Dict[str, Any]]:
    """
    Score detected columns and ensure strict spatial deduplication.
    Framing plans only: suggest missing columns where beams converge.
    Foundation plans: skip beam-support checks and ghost suggestions.
    """
    endpoints: List[tuple] = []
    for r in member_rows:
        if r["kind"] != "beam":
            continue
        g = r["geometry"]
        bdir = g.get("beam_dir")
        for (px, py) in ((g.get("bx1"), g.get("by1")), (g.get("bx2"), g.get("by2"))):
            if px is not None and py is not None:
                endpoints.append((float(px), float(py), bdir))

    columns = [r for r in member_rows if r["kind"] == "column"]

    # 1) Validate detected columns
    for col in columns:
        g = col["geometry"]
        cx, cy = float(g.get("x", 0)), float(g.get("y", 0))
        support = sum(
            1 for (px, py, _bdir) in endpoints
            if abs(px - cx) < endpoint_tol and abs(py - cy) < endpoint_tol
        )
        flags: List[str] = []
        conf = col.get("confidence") or 0.5
        if not is_foundation_plan:
            if support >= 2:
                conf = min(1.0, conf + 0.15)
            elif support == 0:
                flags.append("orphan")
                conf = max(0.1, conf - 0.20)
        if not col.get("section") and not is_foundation_plan:
            flags.append("no_label")
            conf = max(0.1, conf - 0.10)

        g["beam_support"] = support
        g["error_flags"] = flags
        g["symbol"] = g.get("symbol") or "I"
        col["confidence"] = round(conf, 2)
        if (conf < 0.75 or flags) and not is_foundation_plan:
            col["status"] = "need_review"

    # 2) Suggest missing columns at beam-end convergence points (Framing plans only)
    if endpoints and not is_foundation_plan:
        clusters: Dict[tuple, List[tuple]] = {}
        for (px, py, bdir) in endpoints:
            key = (round(px / cluster_tol), round(py / cluster_tol))
            clusters.setdefault(key, []).append((px, py, bdir))

        col_pts = [(float(c["geometry"].get("x", 0)), float(c["geometry"].get("y", 0))) for c in columns]
        suggested = 0
        for pts in clusters.values():
            if suggested >= max_suggestions or len(pts) < min_converging:
                continue
            dirs = {d for (_x, _y, d) in pts if d}
            if dirs and not ({"H", "V"} <= dirs):
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

    # 3) Strict Universal Spatial Deduplication
    # Merge any columns that are within 2.5% of page width of each other into exactly one column
    final_rows: List[Dict[str, Any]] = []
    seen_col_positions: List[Tuple[float, float, int]] = []
    for r in member_rows:
        if r.get("kind") != "column":
            final_rows.append(r)
            continue
        g = r.get("geometry") or {}
        cx = float(g.get("raw_x") if g.get("raw_x") is not None else g.get("x", 0))
        cy = float(g.get("raw_y") if g.get("raw_y") is not None else g.get("y", 0))

        import math
        dup_idx = -1
        for (ex, ey, f_idx) in seen_col_positions:
            if math.hypot(cx - ex, cy - ey) < 0.025:
                dup_idx = f_idx
                break

        if dup_idx >= 0:
            existing = final_rows[dup_idx]
            if not existing.get("section") and r.get("section"):
                final_rows[dup_idx] = r
        else:
            seen_col_positions.append((cx, cy, len(final_rows)))
            final_rows.append(r)

    return final_rows


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
