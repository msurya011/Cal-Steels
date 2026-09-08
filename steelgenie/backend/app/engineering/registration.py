"""
Multi-sheet floor clustering, grid extraction, and page registration.

Implements Phases 1-4 of docs/multi-sheet-3d-architecture.md:
  1. cluster_pages_into_floors  -- group pages into floors by parsed level name
  2. extract_grids_for_page     -- derive + persist labeled grid lines per page
  3. register_floor             -- solve each page's transform into floor-global feet
  4. write_global_geometry      -- write members.geometry.global for a registered page

v1 simplifications (documented, not hidden):
  - Grid *labels* are sequential ("1","2",... / "A","B",...) derived from
    column/beam-endpoint clustering, not OCR'd off grid bubbles (no OCR
    pipeline for bubble text exists yet). This still lets sheets of the same
    floor register against each other correctly as long as extraction runs
    left-to-right / top-to-bottom, which the clustering does.
  - Registration solves translation only (rotation_deg is always 0). This
    matches the common case (sheets tiled in a rectangular grid, no skew
    between zones) seen in the reference screenshots. Full similarity-
    transform solving is flagged as future hardening in the design doc.
  - Uses a spanning-tree propagation from one anchor page per floor, not a
    global least-squares bundle adjustment (also flagged as future work).
"""
from __future__ import annotations

import logging
import math
import os
import re
import sys
import threading
import uuid
from typing import Any, Optional

from app.services.database import get_db
from app.engineering.column_validation import (
    compute_column_confidence,
    check_schedule_count_anomaly,
    validate_column_row,
)
from app.engineering import column_match_engine

logger = logging.getLogger(__name__)

# register_floor() does a full read-recompute-write pass over a floor's
# pages every time it's called -- it's not incremental and it's not
# thread-safe. It used to only ever be called from one place, serially
# (GET /model/merged, on-demand when the 3D view loaded, well after all
# extraction jobs for a session had already finished). Now that extraction
# jobs also call it directly the moment each page finishes (so the 3D
# viewer's fetch doesn't have to do the slow correlation pass itself --
# see analyse.py), two pages extracted back-to-back can trigger two
# concurrent register_floor() calls for the SAME floor from two different
# background-job threads. Each one reads the floor's current state,
# computes transforms, and writes page_registrations back -- interleaved,
# that read-then-write races and one call's result silently clobbers the
# other's, which is what produced sheets falling back to arbitrary "tile"
# placement (visible gaps between fragments) instead of correlating
# against each other. A per-floor lock serializes these so the second
# call always sees the first call's finished result before it starts.
_floor_locks: dict[str, threading.Lock] = {}
_floor_locks_guard = threading.Lock()


def _get_floor_lock(floor_id: str) -> threading.Lock:
    key = str(floor_id)
    with _floor_locks_guard:
        lock = _floor_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _floor_locks[key] = lock
        return lock

GRID_CLUSTER_TOL = 0.02       # fraction-of-page tolerance for clustering member positions into a grid line
GRID_MATCH_REL_TOL = 0.15     # relative tolerance for matching a grid label's feet-position between two pages
# No default floor-height constant here on purpose -- every floor's elevation
# is a real, user-entered T.O.S. (see model.py, which derives it from a
# floor's own pages rather than guessing a storey height).


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cluster(vals: list[float], tol: float = GRID_CLUSTER_TOL) -> list[float]:
    out: list[float] = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _level_name_from_title(title: Optional[str], sheet_no: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Best-effort parse of a page title/sheet number into (level_name, zone_label).

    Examples:
      "Partial Level 04 Framing Plan - Zone A" -> ("Level 04", "Zone A")
      "Third Floor Framing Plan"                -> ("Third Floor", None)
    """
    text = title or sheet_no or ""
    if not text:
        return None, None

    zone_match = re.search(r"\bzone\s*([A-Za-z0-9]+)\b", text, re.IGNORECASE)
    zone_label = f"Zone {zone_match.group(1).upper()}" if zone_match else None

    level_match = re.search(
        r"\b((?:level|floor)\s*\d+|(?:ground|first|second|third|fourth|fifth|sixth|"
        r"seventh|eighth|ninth|tenth|roof|penthouse|basement|mezzanine)\s*floor)\b",
        text, re.IGNORECASE,
    )
    level_name = level_match.group(1).strip().title() if level_match else None

    return level_name, zone_label


_PAGE_PT_SIZE_CACHE = {}
_SCHEDULE_RECORDS_CACHE: dict[str, list] = {}

def clear_registration_caches():
    """Clear in-memory registration and schedule caches."""
    _PAGE_PT_SIZE_CACHE.clear()
    _SCHEDULE_RECORDS_CACHE.clear()

def _page_pt_size(page: dict, db: Any) -> tuple[float, float]:
    """Return (width_pts, height_pts) for a page by opening its source PDF."""
    page_id_str = str(page["id"])
    if page_id_str in _PAGE_PT_SIZE_CACHE:
        return _PAGE_PT_SIZE_CACHE[page_id_str]

    try:
        from app.services.storage import get_storage, LocalStorageAdapter

        drawing_row = db.table("drawings").select("*").eq("id", str(page["drawing_id"])).maybe_single().execute()
        storage = get_storage()
        if drawing_row.data and isinstance(storage, LocalStorageAdapter):
            file_path = storage.local_path(drawing_row.data["storage_key"])
            backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            if backend_dir not in sys.path:
                sys.path.insert(0, backend_dir)
            import fitz
            doc = fitz.open(file_path)
            p = doc[page["idx"]]
            w, h = p.rect.width, p.rect.height
            doc.close()
            _PAGE_PT_SIZE_CACHE[page_id_str] = (w, h)
            return w, h
    except Exception as exc:
        logger.debug("Could not open PDF for page %s pt-size, using default: %s", page.get("id"), exc)
    
    _PAGE_PT_SIZE_CACHE[page_id_str] = (3400.0, 2200.0)
    return 3400.0, 2200.0

def _collect_schedule_records(pages: list[dict], db: Any) -> list:
    """
    Open every page in this project's PDFs and, for any page that mentions a
    column/base-plate schedule, run the Column Schedule table parser (Phase
    4 of the Column Engine -- see app/engineering/column_schedule.py) and
    collect the resulting records. Cheap text pre-check (is_schedule_page)
    before the more expensive table-extraction call, same pattern as the
    is_foundation_plan text-sniff already used elsewhere in this codebase.

    2026-07-28 (user-reported: opening the 3D view took 5+ minutes and hung
    at 95% on a ~15-page project): this function used to open and re-scan
    EVERY page's source PDF from scratch on every single call --
    sync_global_columns() calls it unconditionally on every /model/merged
    request (every time the 3D view is opened), so clicking "3D" repeatedly
    re-ran a full fitz.open() + text scan (+ full table-extraction pass on
    any schedule page) for every page in the project, every time, with
    nothing cached across requests. Per-page results are deterministic for
    a given page (same PDF content in, same schedule records out), so this
    caches them in-memory per page_id -- same pattern already used by
    _PAGE_PT_SIZE_CACHE just above. First 3D-view open after new pages are
    extracted still pays the real cost; every subsequent open reuses the
    cached result instead of re-opening every PDF in the project again.
    """
    try:
        from app.services.storage import get_storage, LocalStorageAdapter
        from app.engineering.column_schedule import is_schedule_page, parse_column_schedule_page
    except Exception as exc:
        logger.debug("Column schedule parser unavailable: %s", exc)
        return []

    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    try:
        import fitz
    except Exception:
        return []

    storage = get_storage()
    if not isinstance(storage, LocalStorageAdapter):
        return []

    # Split out pages whose schedule records are already cached from this
    # process's lifetime -- only the uncached remainder needs a PDF opened.
    uncached_pages = []
    records = []
    for page in pages:
        page_id_str = str(page.get("id"))
        cached = _SCHEDULE_RECORDS_CACHE.get(page_id_str)
        if cached is not None:
            records.extend(cached)
        else:
            uncached_pages.append(page)

    if not uncached_pages:
        return records

    drawing_ids = list({p["drawing_id"] for p in uncached_pages if p.get("drawing_id")})
    drawing_rows = {
        d["id"]: d for d in
        (db.table("drawings").select("*").in_("id", drawing_ids).execute().data or [])
    }

    docs_cache: dict[str, Any] = {}
    for page in uncached_pages:
        page_id_str = str(page.get("id"))
        drawing = drawing_rows.get(page.get("drawing_id"))
        if not drawing:
            continue
        try:
            doc = docs_cache.get(drawing["id"])
            if doc is None:
                file_path = storage.local_path(drawing["storage_key"])
                doc = fitz.open(file_path)
                docs_cache[drawing["id"]] = doc
            pdf_page = doc[page["idx"]]
            if not is_schedule_page(pdf_page):
                _SCHEDULE_RECORDS_CACHE[page_id_str] = []
                continue
            page_records = parse_column_schedule_page(pdf_page, page_idx=page["idx"])
            _SCHEDULE_RECORDS_CACHE[page_id_str] = page_records
            records.extend(page_records)
        except Exception as exc:
            logger.debug("Schedule parse failed for page %s: %s", page.get("id"), exc)
            continue

    for doc in docs_cache.values():
        try:
            doc.close()
        except Exception:
            pass

    return records


def _ppf(scale_ratio: float) -> float:
    """points-per-foot, matching structural_schema._ppf()."""
    return 864.0 / (scale_ratio or 96.0)


def _page_ft_span(page: dict, db: Any) -> tuple[float, float]:
    """(feet spanned by fraction 1.0 in x, feet spanned by fraction 1.0 in y)."""
    w_pts, h_pts = _page_pt_size(page, db)
    ppf = _ppf(page.get("scale_num") or 96.0)
    return w_pts / ppf, h_pts / ppf


# ---------------------------------------------------------------------------
# Phase 1: floor clustering
# ---------------------------------------------------------------------------

TOS_MATCH_TOL_FT = 0.25  # pages within 3 inches of Top-of-Steel share a floor (user-confirmed 2026-07-10)



def _tos_key(tos_ft: Optional[float], existing_keys: list[float]) -> Optional[float]:
    """Snap a page's tos_ft onto an existing floor's TOS bucket if it's within
    tolerance, otherwise return it as a new bucket. Keeps '12.0' and '11.98'
    (rounding noise from ft-in-fraction parsing) in the same floor while still
    treating genuinely different elevations as different floors."""
    if tos_ft is None:
        return None
    for k in existing_keys:
        if abs(k - tos_ft) <= TOS_MATCH_TOL_FT:
            return k
    return tos_ft


def _floor_key(
    level_name: Optional[str], tos_ft: Optional[float], existing_floors: list[dict]
) -> Optional[tuple]:
    """Stage 1 of the 2026-07-17 SteelGenie rebuild (live-verified): real
    floor identity there is Level Name + elevation TOGETHER, not a bare TOS
    number matched across pages. Snaps a page's (level_name, tos_ft) onto an
    existing floor only when BOTH the level name matches (exact string, or
    both absent) AND the elevation is within TOS_MATCH_TOL_FT -- otherwise
    treats it as a new floor bucket.

    Deliberately a narrowing of the old _tos_key-only rule, never a
    widening: adding the level-name condition can only ever SPLIT floors
    that used to be (incorrectly) merged just because they shared a TOS
    number, it can never merge floors that were previously kept separate.
    That direction-of-change matters -- it's what keeps this additive
    rather than a repeat of the earlier full floor-registration rewrite
    that had to be reverted.
    """
    if tos_ft is None:
        return None
    for f in existing_floors:
        f_tos = f.get("elevation_ft")
        if f_tos is None:
            continue
        if (f.get("level_name") or None) != (level_name or None):
            continue
        if abs(f_tos - tos_ft) <= TOS_MATCH_TOL_FT:
            return (f.get("level_name"), f_tos)
    return (level_name, tos_ft)


def cluster_pages_into_floors(project_id: str) -> dict:
    """Group all pages of a project into floors.

    Grouping key, in priority order:
      1. Top of Steel (tos_ft) -- this is the primary, authoritative key.
         Any two pages across any drawings that share the same TOS value are
         the same physical floor and get merged into one 3D level, exactly
         like SteelGenie: enter 12'-0" on one sheet and 12'-0" on another
         and they build as the same floor, regardless of sheet title/number.
      2. Parsed level_name from the sheet title (fallback, only used when a
         page has no tos_ft set yet).
      3. The page on its own (fallback, preserves single-sheet behavior).

    Pages already linked to a floor that has a real TOS (elevation_ft is not
    None) are left alone -- re-running this is safe and incremental for
    them. But a page that's still sitting on a *placeholder* floor (created
    before it had a TOS at all, back when this function's only option was
    "one floor per page") is re-evaluated every run: once that page gets a
    real TOS, it's pulled off the placeholder and grouped with any other
    page that shares the same TOS, exactly like SteelGenie. Without this,
    pages that were extracted before TOS was a required field stay stuck as
    permanently isolated floors forever, even after their TOS is filled in.
    """
    db = get_db()
    drawings = db.table("drawings").select("id").eq("project_id", str(project_id)).execute().data or []
    drawing_ids = [d["id"] for d in drawings]
    all_pages: list[dict] = []
    if drawing_ids:
        all_pages = db.table("pages").select("*").in_("drawing_id", drawing_ids).execute().data or []

    parsed: dict[str, tuple[Optional[str], Optional[str]]] = {}
    for p in all_pages:
        level_name, zone_label = _level_name_from_title(p.get("title"), p.get("sheet_no"))
        parsed[p["id"]] = (level_name, zone_label)
        if p.get("level_name") != level_name or p.get("zone_label") != zone_label:
            db.table("pages").update({"level_name": level_name, "zone_label": zone_label}).eq("id", p["id"]).execute()

    all_links = db.table("page_floor_links").select("*").execute().data or []
    all_floors = db.table("floors").select("*").eq("project_id", str(project_id)).execute().data or []
    floors_by_id = {f["id"]: f for f in all_floors}
    link_by_page = {l["page_id"]: l for l in all_links}

    unlinked: list[dict] = []
    reclustered_floor_ids: set[str] = set()
    stale_page_ids: set[str] = set()
    for p in all_pages:
        link = link_by_page.get(p["id"])
        if link is None:
            unlinked.append(p)
            continue
        floor = floors_by_id.get(link["floor_id"])
        floor_is_placeholder = floor is not None and floor.get("elevation_ft") is None
        # Bug fix (2026-07-15, confirmed with runtime evidence via
        # debug_column_trace before any code was touched -- see chat trace
        # for the Bayhealth project): the placeholder-only check above never
        # frees a page whose floor already carries a REAL elevation. If that
        # page's own tos_ft is later edited to a different value, the page
        # stays wired to the old (now-wrong) floor forever, and every column
        # anchored to it silently gets zero-height geometry downstream. Widen
        # the trigger to also catch this "stale real-elevation" case, not
        # just the "still on a null-elevation placeholder" case. This is
        # intentionally the ONLY change to this function -- no change to the
        # TOS-bucketing (_tos_key), clustering, or beam-connectivity logic
        # below, per explicit instruction to keep the fix minimal/targeted.
        floor_is_stale = (
            floor is not None
            and floor.get("elevation_ft") is not None
            and p.get("tos_ft") is not None
            and abs(floor["elevation_ft"] - p["tos_ft"]) > TOS_MATCH_TOL_FT
        )
        # Stage 1 addition (2026-07-17 rebuild, additive alongside the
        # floor_is_stale fix above -- that check and its "ONLY change"
        # comment are left untouched per explicit prior instruction). Same
        # elevation bucket, but this page's own parsed level_name disagrees
        # with the floor it's currently linked to -- real floor identity on
        # SteelGenie is Level Name + elevation together (see _floor_key), so
        # this is the same kind of staleness, just from the other half of
        # the compound key. Only fires when the page actually HAS a parsed
        # level_name to compare (never overrides a page with no title info).
        floor_level_mismatch = (
            floor is not None
            and floor.get("elevation_ft") is not None
            and p.get("tos_ft") is not None
            and abs(floor["elevation_ft"] - p["tos_ft"]) <= TOS_MATCH_TOL_FT
            and parsed[p["id"]][0] is not None
            and (floor.get("level_name") or None) != parsed[p["id"]][0]
        )
        if (floor_is_placeholder or floor_is_stale or floor_level_mismatch) and p.get("tos_ft") is not None:
            if floor_is_stale:
                logger.info(
                    "cluster_pages_into_floors: page %s TOS/floor mismatch detected -- "
                    "current floor '%s' elevation=%s, page tos_ft=%s. Detaching page and "
                    "reassigning...",
                    p["id"], floor.get("name"), floor.get("elevation_ft"), p.get("tos_ft"),
                )
            if floor_level_mismatch:
                logger.info(
                    "cluster_pages_into_floors: page %s level-name mismatch detected -- "
                    "current floor '%s' level_name=%s, page level_name=%s (same elevation "
                    "bucket). Detaching page and reassigning...",
                    p["id"], floor.get("name"), floor.get("level_name"), parsed[p["id"]][0],
                )
            # This page now has a real TOS but is either still parked on the
            # single-page placeholder floor created before TOS existed, its
            # TOS has since diverged from the (real) elevation of the floor
            # it's still linked to, or its Level Name disagrees with that
            # floor's -- free it up either way so it can be grouped by the
            # compound (level_name, TOS) key below.
            db.table("page_floor_links").delete().eq("page_id", p["id"]).execute()
            reclustered_floor_ids.add(floor["id"])
            unlinked.append(p)
            if floor_is_stale or floor_level_mismatch:
                stale_page_ids.add(p["id"])
                logger.info(
                    "cluster_pages_into_floors: page %s detached from floor '%s' (elev=%s); "
                    "will be reassigned to a floor matching tos_ft=%s below.",
                    p["id"], floor.get("name"), floor.get("elevation_ft"), p.get("tos_ft"),
                )

    # Placeholder floors left with zero pages after the re-link above are
    # stale and would otherwise clutter the floor list / 3D scope dropdown.
    if reclustered_floor_ids:
        remaining_links = db.table("page_floor_links").select("*").execute().data or []
        still_used = {l["floor_id"] for l in remaining_links}
        for fid in reclustered_floor_ids:
            if fid not in still_used:
                db.table("floors").delete().eq("id", fid).execute()

    # Stage 1 (2026-07-17 rebuild): group by the compound (level_name,
    # elevation) key instead of TOS alone -- see _floor_key. known_floors
    # accumulates as we go, same incremental-snapping pattern the old
    # known_tos list used, just carrying level_name alongside each bucket.
    floor_groups: dict[tuple, list[dict]] = {}
    remaining: list[dict] = []
    known_floors: list[dict] = [
        {"elevation_ft": f["elevation_ft"], "level_name": f.get("level_name")}
        for f in all_floors if f.get("elevation_ft") is not None
    ]
    for p in unlinked:
        tos = p.get("tos_ft")
        if tos is None:
            remaining.append(p)
            continue
        level_name, _zone = parsed[p["id"]]
        key = _floor_key(level_name, tos, known_floors)
        if key is not None and not any(
            kf.get("level_name") == key[0] and kf.get("elevation_ft") == key[1] for kf in known_floors
        ):
            known_floors.append({"elevation_ft": key[1], "level_name": key[0]})
        floor_groups.setdefault(key, []).append(p)

    name_groups: dict[str, list[dict]] = {}
    for p in remaining:
        level_name, _zone = parsed[p["id"]]
        key = level_name or f"__page__{p['id']}"
        name_groups.setdefault(key, []).append(p)

    existing_floors_by_key = {
        (f.get("level_name"), f["elevation_ft"]): f
        for f in (db.table("floors").select("*").eq("project_id", str(project_id)).execute().data or [])
        if f.get("elevation_ft") is not None
    }

    created_floors = 0
    linked_pages = 0

    def _link_group(pages_in_group: list[dict], floor_row: dict) -> None:
        nonlocal linked_pages
        for p in pages_in_group:
            _level, zone = parsed[p["id"]]
            db.table("page_floor_links").upsert({
                "page_id": p["id"],
                "floor_id": floor_row["id"],
                "zone_label": zone,
            }).execute()
            linked_pages += 1
            if p["id"] in stale_page_ids:
                logger.info(
                    "cluster_pages_into_floors: page %s reassigned. Assigned floor: %s (elev=%s)",
                    p["id"], floor_row.get("name"), floor_row.get("elevation_ft"),
                )

    for key, pages_in_group in floor_groups.items():
        level_name_key, tos = key
        pages_in_group.sort(key=lambda p: p.get("idx", 0))
        target_floor = existing_floors_by_key.get(key)
        if target_floor is None:
            floor_name = f"TOS {tos:.0f}'-0\"" if tos == int(tos) else f"TOS {tos:.2f}'"
            first_named = level_name_key or next(
                (p.get("level_name") for p in pages_in_group if p.get("level_name")), None
            )
            if first_named:
                floor_name = first_named
            sort_order = min(p.get("idx", 0) for p in pages_in_group)
            target_floor = db.table("floors").insert({
                "project_id": str(project_id),
                "name": floor_name,
                "elevation_ft": tos,
                "sort_order": sort_order,
                "status": "draft",
            }).execute().data[0]
            existing_floors_by_key[key] = target_floor
            created_floors += 1
        _link_group(pages_in_group, target_floor)

    for key, pages_in_group in name_groups.items():
        pages_in_group.sort(key=lambda p: p.get("idx", 0))
        first = pages_in_group[0]
        floor_name = first.get("level_name") or first.get("title") or f"Page {first.get('idx', 0) + 1}"
        sort_order = min(p.get("idx", 0) for p in pages_in_group)
        floor_row = db.table("floors").insert({
            "project_id": str(project_id),
            "name": floor_name,
            "elevation_ft": first.get("tos_ft"),
            "sort_order": sort_order,
            "status": "draft",
        }).execute().data[0]
        created_floors += 1
        _link_group(pages_in_group, floor_row)

    return {"floors_created": created_floors, "pages_linked": linked_pages}


# ---------------------------------------------------------------------------
# Phase 2: grid extraction
# ---------------------------------------------------------------------------

def extract_grids_for_page(page_id: str) -> dict:
    """Fallback ONLY: derive idealized grid lines from column/beam-endpoint
    clustering and persist them with sequential labels ("1","2"... / "A","B"...).

    This is a last resort for pages where the real grid-bubble text couldn't
    be read off the sheet at all (e.g. a scanned/raster page with no vector
    text, or a page whose bubbles fell outside the detection zone). Whenever
    real bubble text WAS found, workers/analyse.py already persisted those
    grids directly (source='ai', confidence=0.9) right after extraction --
    this function must not clobber them with guessed sequential numbers, so
    it no-ops if any high-confidence (real-label) grid already exists for
    this page.
    """
    db = get_db()
    existing_real = db.table("grids").select("*").eq("page_id", str(page_id)).execute().data or []
    if any((g.get("confidence") or 0) >= 0.8 for g in existing_real):
        return {"v_grid": [], "h_grid": [], "written": 0, "skipped": "real grid labels already persisted"}

    members = db.table("members").select("*").eq("page_id", str(page_id)).neq("status", "excluded").execute().data or []

    xs: list[float] = []
    ys: list[float] = []
    for m in members:
        geo = m.get("geometry") or {}
        if m.get("kind") == "column":
            x, y = geo.get("x"), geo.get("y")
            if x is not None and y is not None:
                xs.append(x)
                ys.append(y)
        else:
            for bx, by in ((geo.get("bx1"), geo.get("by1")), (geo.get("bx2"), geo.get("by2"))):
                if bx is not None and by is not None:
                    xs.append(bx)
                    ys.append(by)

    v_grid = _cluster(xs)
    h_grid = _cluster(ys)

    # Delete existing ai-source grids in one bulk operation (one file write)
    # instead of one delete per row (N file writes). The old pattern caused
    # one full local_db.json flush per grid line, which on a 32-page project
    # with ~10 grids/page = 320 writes x ~0.75s = ~4 min stalled at 90%.
    stale_ids = [g["id"] for g in existing_real if g.get("source") == "ai"]
    if stale_ids:
        from app.services.database import bulk_delete_by_id
        bulk_delete_by_id("grids", stale_ids)

    # Build all grid rows and insert as a single batch (one file write total)
    grid_rows = []
    for i, x in enumerate(v_grid):
        grid_rows.append({
            "page_id": str(page_id), "axis": "x", "label": str(i + 1),
            "position": x, "confidence": 0.5, "source": "ai",
        })

    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for i, y in enumerate(h_grid):
        label = letters[i] if i < len(letters) else str(i + 1)
        grid_rows.append({
            "page_id": str(page_id), "axis": "y", "label": label,
            "position": y, "confidence": 0.5, "source": "ai",
        })

    written = len(grid_rows)
    if grid_rows:
        db.table("grids").insert(grid_rows).execute()

    return {"v_grid": v_grid, "h_grid": h_grid, "written": written}


# ---------------------------------------------------------------------------
# Phase 3: registration engine
# ---------------------------------------------------------------------------

CORR_MIN_MATCHES = 2   # minimum matched grid lines on an axis before a correlation-based offset is trusted
DEDUP_TOL_FT = 0.5     # global-feet tolerance for treating two members from different pages as the same physical element


def _page_grid_positions(page_id: str, db: Any) -> dict[str, list[dict]]:
    """This page's own grid lines, split by axis, as raw {label, position}
    rows (position is still in this page's own 0..1 fraction space)."""
    grids = db.table("grids").select("*").eq("page_id", str(page_id)).execute().data or []
    out: dict[str, list[dict]] = {"x": [], "y": []}
    for g in grids:
        out.setdefault(g["axis"], []).append(g)
    return out


def _global_grid_positions(page_id: str, tx: float, ty: float, ft_x: float, ft_y: float, db: Any) -> dict[str, list[tuple[str, float, float]]]:
    """An already-registered page's grid lines converted to floor-global
    feet, as (label, position_ft, confidence) triples per axis."""
    local = _page_grid_positions(page_id, db)
    out: dict[str, list[tuple[str, float, float]]] = {"x": [], "y": []}
    for g in local.get("x", []):
        out["x"].append((g["label"], tx + g["position"] * ft_x, g.get("confidence", 0.5)))
    for g in local.get("y", []):
        out["y"].append((g["label"], ty + g["position"] * ft_y, g.get("confidence", 0.5)))
    return out


def _match_by_label(
    new_local: list[dict], ref_global: list[tuple[str, float, float]], ft_scale: float
) -> tuple[Optional[float], float, int]:
    """Pass A: align by identical grid-bubble label text -- the same
    physical grid line ("Grid 4", "Grid C") reads the same label on every
    sheet it appears on, so a shared label is an exact registration key.
    Only matches if both grids have real OCR'd labels (confidence >= 0.8).
    Returns (offset_ft, confidence, matched_count)."""
    ref_by_label: dict[str, list[float]] = {}
    for label, pos_ft, conf in ref_global:
        if conf >= 0.8:
            ref_by_label.setdefault(label, []).append(pos_ft)

    offsets: list[float] = []
    for g in new_local:
        if g.get("confidence", 0.5) >= 0.8:
            local_ft = g["position"] * ft_scale
            for ref_pos in ref_by_label.get(g["label"], []):
                offsets.append(ref_pos - local_ft)

    if not offsets:
        return None, 0.0, 0

    offsets.sort()
    median_offset = offsets[len(offsets) // 2]
    spread = offsets[-1] - offsets[0]
    confidence = len(offsets) / max(len(new_local), 1)
    if spread > 3.0:
        # Matched labels disagree by more than 3ft -- likely a coincidental
        # label collision (e.g. two different sheets both restarting at "1"),
        # not a real shared grid line. Don't trust it as much.
        confidence *= 0.3
    return median_offset, confidence, len(offsets)


def _match_by_correlation(
    new_local: list[dict], ref_global: list[tuple[str, float, float]], ft_scale: float, tol_ft: float
) -> tuple[Optional[float], float, int]:
    """Pass B fallback: when labels don't match (sequential/guessed labels
    restart per page, see extract_grids_for_page docstring), try every
    pairwise offset between this page's grid spacing and the reference
    page's, and keep whichever offset makes the most lines coincide within
    tol_ft -- the same idea as a 1D cross-correlation."""
    local_positions = [g["position"] * ft_scale for g in new_local]
    ref_positions = [pos for _label, pos, _conf in ref_global]
    if not local_positions or not ref_positions:
        return None, 0.0, 0

    import bisect
    ref_sorted = sorted(ref_positions)
    best_offset: Optional[float] = None
    best_count = 0
    for lp in local_positions:
        for rp in ref_positions:
            candidate = rp - lp
            count = 0
            for p in local_positions:
                target = p + candidate
                idx = bisect.bisect_left(ref_sorted, target)
                if idx < len(ref_sorted) and abs(ref_sorted[idx] - target) <= tol_ft:
                    count += 1
                elif idx > 0 and abs(ref_sorted[idx - 1] - target) <= tol_ft:
                    count += 1
            if count > best_count:
                best_count = count
                best_offset = candidate

    if best_offset is None or best_count < CORR_MIN_MATCHES:
        return None, 0.0, 0

    confidence = best_count / max(len(local_positions), len(ref_positions))
    return best_offset, confidence, best_count


def _dedup_floor_members(floor_id: str, db: Any) -> dict:
    """After every page of a floor has global geometry, collapse members
    that represent the same physical element extracted twice (once from
    each of two overlapping/adjacent sheets) instead of leaving duplicates
    in the model. Never deletes -- marks the losing copy status='excluded'
    (same convention used for suggested/rejected columns elsewhere) so it
    stays auditable and reversible."""
    links = db.table("page_floor_links").select("*").eq("floor_id", str(floor_id)).execute().data or []
    page_ids = [l["page_id"] for l in links]
    members: list[dict] = []
    for pid in page_ids:
        members.extend(db.table("members").select("*").eq("page_id", pid).neq("status", "excluded").execute().data or [])

    def key_for(m: dict) -> Optional[tuple]:
        g = (m.get("geometry") or {}).get("global")
        if not g:
            return None
        kind = m.get("kind")
        section = m.get("section") or ""
        if g.get("gx1_ft") is not None and g.get("gx2_ft") is not None:
            a = (round(g["gx1_ft"] / DEDUP_TOL_FT), round(g["gy1_ft"] / DEDUP_TOL_FT))
            b = (round(g["gx2_ft"] / DEDUP_TOL_FT), round(g["gy2_ft"] / DEDUP_TOL_FT))
            return (kind, section, tuple(sorted([a, b])))
        if g.get("gx_ft") is not None:
            return (kind, section, (round(g["gx_ft"] / DEDUP_TOL_FT), round(g["gy_ft"] / DEDUP_TOL_FT)))
        return None

    groups: dict[tuple, list[dict]] = {}
    for m in members:
        k = key_for(m)
        if k is not None:
            groups.setdefault(k, []).append(m)

    excluded = 0
    pending = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        # Prefer a labeled member over an unlabeled guess, then higher
        # extraction confidence, as the surviving copy.
        group.sort(key=lambda m: (bool((m.get("geometry") or {}).get("unlabeled")), -(m.get("confidence") or 0)))
        for loser in group[1:]:
            pending[loser["id"]] = {"status": "excluded", "excluded_reason": "duplicate_merged"}
            excluded += 1

    if pending:
        from app.services.database import bulk_update_by_id
        bulk_update_by_id("members", pending)

    return {"groups_checked": len(groups), "duplicates_excluded": excluded}


def register_floor(floor_id: str) -> dict:
    """Solve a translation-only transform for every page of a floor into a
    shared floor-global feet coordinate system, then deduplicate members in
    any overlap between sheets. Writes page_registrations rows.

    Multi-sheet registration tries, in order, per page:
      Pass A (grid_label)       -- match identical grid-bubble label text
                                    against every already-registered page's
                                    grids. Exact when real bubble text was
                                    read off both sheets.
      Pass B (grid_correlation) -- when labels don't line up (sequential/
                                    guessed labels restart per page), find
                                    the offset that makes the most grid
                                    lines coincide, like a 1D cross-
                                    correlation.
      Fallback (tile)           -- only when a page shares no usable grid
                                    evidence with anything already placed.
                                    Last resort so the page isn't dropped
                                    from the model; always forces the floor
                                    to need_review.

    Thread-safe: serialized per floor_id via _get_floor_lock so two
    extraction jobs finishing close together (or an extraction job racing
    the 3D view's on-demand call) can't interleave their read-recompute-
    write passes -- see the lock's docstring above for the real bug this
    prevents.
    """
    with _get_floor_lock(floor_id):
        return _register_floor_impl(floor_id)


def _register_floor_impl(floor_id: str) -> dict:
    db = get_db()
    links = db.table("page_floor_links").select("*").eq("floor_id", str(floor_id)).execute().data or []
    if not links:
        return {"registered": 0, "confidence_avg": None}

    pages = {}
    for link in links:
        pg = db.table("pages").select("*").eq("id", link["page_id"]).maybe_single().execute().data
        if pg:
            pages[pg["id"]] = pg

    if not pages:
        return {"registered": 0, "confidence_avg": None}

    for pid in pages:
        existing_grids = db.table("grids").select("*").eq("page_id", pid).execute().data
        if not existing_grids:
            extract_grids_for_page(pid)

    ft_span_by_page: dict[str, tuple[float, float]] = {
        pid: _page_ft_span(pages[pid], db) for pid in pages
    }

    def sort_key(pid: str) -> tuple:
        p = pages[pid]
        return (p.get("idx", 0), p.get("zone_label") or "")

    ordered = sorted(pages.keys(), key=sort_key)

    registered: dict[str, dict] = {}  # page_id -> {tx, ty, ft_x, ft_y}
    results: list[dict] = []
    confidences: list[float] = []
    tile_cursor = 0.0
    TILE_GAP_FT = 2.0  # small gap at the seam so tiled sheets' members don't touch

    # Query already-registered pages in other floors of the same project
    floor_row = db.table("floors").select("project_id").eq("id", str(floor_id)).maybe_single().execute().data
    project_id = floor_row.get("project_id") if floor_row else None

    project_registered: dict[str, dict] = {}
    if project_id:
        project_floors = db.table("floors").select("id").eq("project_id", str(project_id)).execute().data or []
        project_floor_ids = [f["id"] for f in project_floors if f["id"] != str(floor_id)]
        if project_floor_ids:
            project_regs = db.table("page_registrations").select("*").in_("floor_id", project_floor_ids).execute().data or []
            for r in project_regs:
                project_registered[r["page_id"]] = {
                    "tx": r["tx_ft"],
                    "ty": r["ty_ft"],
                    "ft_x": r["ft_per_pct_x"],
                    "ft_y": r["ft_per_pct_y"],
                }

    for i, pid in enumerate(ordered):
        ft_x, ft_y = ft_span_by_page[pid]
        local = _page_grid_positions(pid, db)

        # Build reference grids from other registered pages on this floor,
        # or already-registered pages on other floors of the same project
        ref_x = []
        ref_y = []
        all_available_refs = {**project_registered, **registered}
        for rpid, r in all_available_refs.items():
            g = _global_grid_positions(rpid, r["tx"], r["ty"], r["ft_x"], r["ft_y"], db)
            ref_x.extend(g["x"])
            ref_y.extend(g["y"])

        if i == 0 and len(all_available_refs) == 0:
            tx, ty, confidence, method = 0.0, 0.0, 1.0, "identity"
        else:
            tx_a, conf_x_a, n_x_a = _match_by_label(local.get("x", []), ref_x, ft_x)
            ty_a, conf_y_a, n_y_a = _match_by_label(local.get("y", []), ref_y, ft_y)

            if tx_a is not None and ty_a is not None and n_x_a and n_y_a:
                tx, ty = tx_a, ty_a
                confidence = (conf_x_a + conf_y_a) / 2
                method = "grid_label"
            else:
                tx_b, conf_x_b, _n_x_b = _match_by_correlation(local.get("x", []), ref_x, ft_x, GRID_CLUSTER_TOL * ft_x)
                ty_b, conf_y_b, _n_y_b = _match_by_correlation(local.get("y", []), ref_y, ft_y, GRID_CLUSTER_TOL * ft_y)

                if tx_b is not None and ty_b is not None:
                    tx, ty = tx_b, ty_b
                    confidence = (conf_x_b + conf_y_b) / 2
                    method = "grid_correlation"
                elif tx_a is not None or tx_b is not None or ty_a is not None or ty_b is not None:
                    # Usable offset on one axis only -- use it, tile the other.
                    tx = tx_a if tx_a is not None else (tx_b if tx_b is not None else tile_cursor)
                    ty = ty_a if ty_a is not None else (ty_b if ty_b is not None else 0.0)
                    confidence = 0.35
                    method = "partial_match"
                else:
                    if i == 0:
                        # First page of floor: stack it at 0,0 relative to project origin
                        # rather than tiling it horizontally next to other floors
                        tx, ty = 0.0, 0.0
                        confidence = 0.5
                        method = "identity"
                    else:
                        tx, ty = tile_cursor, 0.0
                        confidence = 0.15
                        method = "tile"

                if method == "tile":
                    tile_cursor += ft_x + TILE_GAP_FT

        registered[pid] = {"tx": tx, "ty": ty, "ft_x": ft_x, "ft_y": ft_y}
        confidences.append(confidence)
        db_method = {
            "grid_label": "grid_match",
            "grid_correlation": "grid_match",
            "partial_match": "grid_match",
            "match_line": "match_line",
            "manual": "manual",
            "identity": "identity",
            "tile": "identity",
        }.get(method, "identity")
        db.table("page_registrations").upsert({
            "page_id": pid, "floor_id": str(floor_id),
            "tx_ft": tx, "ty_ft": ty, "rotation_deg": 0,
            "ft_per_pct_x": ft_x, "ft_per_pct_y": ft_y,
            "anchor": i == 0,
            "confidence": confidence,
            "method": db_method,
        }).execute()
        results.append({"page_id": pid, "confidence": confidence, "method": method})

    avg_conf = sum(confidences) / len(confidences)
    # Only trust a floor as final when every page registered off real grid
    # evidence (label match or correlation) -- any page that fell back to a
    # tile-of-last-resort guess means the alignment needs a human to confirm
    # it via PATCH /pages/{page_id}/registration before it's treated as truth.
    floor_status = "registered" if avg_conf >= 0.6 and all(r["method"] != "tile" for r in results) else "need_review"
    db.table("floors").update({"status": floor_status}).eq("id", str(floor_id)).execute()

    # Write global geometry for ALL pages of this floor in a SINGLE file write.
    # Previously this was a per-page loop: write_global_geometry(pid) for each
    # ordered page.  Each call does a full bulk_update_by_id → json.dump of the
    # entire 65 MB local_db.json (~2.8s). With N pages on one floor that's
    # N × 2.8s of pure I/O while the job sits at 90%, which is what causes
    # the "Extraction timed out" toast on multi-page projects.
    write_global_geometry_multi(ordered)

    dedup_result = _dedup_floor_members(str(floor_id), db)

    return {"registered": len(ordered), "confidence_avg": avg_conf, "results": results, "dedup": dedup_result}


# ---------------------------------------------------------------------------
# Phase 4: global geometry
# ---------------------------------------------------------------------------

def member_global_endpoints(member: dict, page: dict, db: Any) -> dict:
    """Return floor-global feet coordinates for one member, using
    geometry.global if the page has already been registered, otherwise
    falling back to an identity transform (tx=ty=0, this page's own
    fraction->feet span) so unregistered / single-sheet projects behave
    exactly like the pre-multi-sheet pipeline."""
    geo = member.get("geometry") or {}
    global_geo = geo.get("global")
    if global_geo:
        return global_geo

    ft_x, ft_y = _page_ft_span(page, db)
    x, y = geo.get("x"), geo.get("y")
    out: dict[str, Any] = {"floor_id": None}
    if x is not None and y is not None:
        out["gx_ft"] = round(x * ft_x, 3)
        out["gy_ft"] = round(y * ft_y, 3)
    if geo.get("bx1") is not None and geo.get("by1") is not None:
        out["gx1_ft"] = round(geo["bx1"] * ft_x, 3)
        out["gy1_ft"] = round(geo["by1"] * ft_y, 3)
    if geo.get("bx2") is not None and geo.get("by2") is not None:
        out["gx2_ft"] = round(geo["bx2"] * ft_x, 3)
        out["gy2_ft"] = round(geo["by2"] * ft_y, 3)
    return out


def page_registration_transform(page: dict, db: Any) -> dict:
    """(tx_ft, ty_ft, ft_x, ft_y) for a page -- from page_registrations if it
    has been registered, otherwise an identity transform using the page's
    own fraction->feet span. Shared by member and grid-line global-coordinate
    conversion so both use exactly the same placement."""
    reg = db.table("page_registrations").select("*").eq("page_id", str(page["id"])).maybe_single().execute().data
    if reg:
        return {"tx": reg["tx_ft"], "ty": reg["ty_ft"], "ft_x": reg["ft_per_pct_x"], "ft_y": reg["ft_per_pct_y"]}
    ft_x, ft_y = _page_ft_span(page, db)
    return {"tx": 0.0, "ty": 0.0, "ft_x": ft_x, "ft_y": ft_y}


def grid_lines_global(page: dict, db: Any) -> list[dict]:
    """Return this page's labeled grid lines (see extract_grids_for_page)
    converted to floor-global feet, spanning the full extent of the page
    they were extracted from. Used to draw real labeled reference grids in
    the 3D viewer instead of a generic unlabeled floor grid."""
    t = page_registration_transform(page, db)
    grids = db.table("grids").select("*").eq("page_id", str(page["id"])).execute().data or []
    out = []
    for g in grids:
        if g["axis"] == "x":
            gx = t["tx"] + g["position"] * t["ft_x"]
            out.append({
                "axis": "x", "label": g["label"], "page_id": page["id"],
                "gx1": gx, "gy1": t["ty"], "gx2": gx, "gy2": t["ty"] + t["ft_y"],
            })
        else:
            gy = t["ty"] + g["position"] * t["ft_y"]
            out.append({
                "axis": "y", "label": g["label"], "page_id": page["id"],
                "gx1": t["tx"], "gy1": gy, "gx2": t["tx"] + t["ft_x"], "gy2": gy,
            })
    return out


def write_global_geometry(page_id: str) -> dict:
    """Apply the page's resolved registration transform to every member's
    geometry and write the result into geometry.global (floor-global feet).
    No-ops (returns written=0) if the page has no registration yet."""
    db = get_db()
    reg = db.table("page_registrations").select("*").eq("page_id", str(page_id)).maybe_single().execute().data
    if not reg:
        return {"written": 0}

    tx, ty = reg["tx_ft"], reg["ty_ft"]
    ft_x, ft_y = reg["ft_per_pct_x"], reg["ft_per_pct_y"]
    floor_id = reg["floor_id"]

    members = db.table("members").select("*").eq("page_id", str(page_id)).execute().data or []
    # Batch every member's geometry update into one file write instead of one
    # write per member -- see bulk_update_by_id's docstring for why (this loop
    # is exactly the code path that corrupted local_db.json once already).
    from app.services.database import bulk_update_by_id
    pending: dict[str, dict] = {}
    for m in members:
        geo = dict(m.get("geometry") or {})
        x, y = geo.get("x"), geo.get("y")
        if x is None or y is None:
            continue
        global_geo: dict[str, Any] = {
            "floor_id": floor_id,
            "gx_ft": round(tx + x * ft_x, 3),
            "gy_ft": round(ty + y * ft_y, 3),
        }
        if geo.get("bx1") is not None and geo.get("by1") is not None:
            global_geo["gx1_ft"] = round(tx + geo["bx1"] * ft_x, 3)
            global_geo["gy1_ft"] = round(ty + geo["by1"] * ft_y, 3)
        if geo.get("bx2") is not None and geo.get("by2") is not None:
            global_geo["gx2_ft"] = round(tx + geo["bx2"] * ft_x, 3)
            global_geo["gy2_ft"] = round(ty + geo["by2"] * ft_y, 3)

        geo["global"] = global_geo
        pending[m["id"]] = {"geometry": geo}

    written = bulk_update_by_id("members", pending)
    return {"written": written}


def write_global_geometry_multi(page_ids: list[str]) -> dict:
    """Apply registration transforms for MULTIPLE pages in ONE file write.

    register_floor() used to call write_global_geometry() in a per-page loop,
    causing one full local_db.json write per page (~2.8s each on this project).
    A 10-page floor cost ~28s; a 32-page floor over a minute — exactly enough
    to trip the frontend 120s stall-timeout at 90%. This merges all pages'
    member geometry updates into a single bulk_update_by_id call so the whole
    floor always takes one write regardless of page count.
    """
    db = get_db()
    all_pending: dict[str, dict] = {}
    total_pages = 0
    for page_id in page_ids:
        reg = db.table("page_registrations").select("*").eq("page_id", str(page_id)).maybe_single().execute().data
        if not reg:
            continue
        tx, ty = reg["tx_ft"], reg["ty_ft"]
        ft_x, ft_y = reg["ft_per_pct_x"], reg["ft_per_pct_y"]
        floor_id = reg["floor_id"]
        members = db.table("members").select("*").eq("page_id", str(page_id)).execute().data or []
        total_pages += 1
        for m in members:
            geo = dict(m.get("geometry") or {})
            x, y = geo.get("x"), geo.get("y")
            if x is None or y is None:
                continue
            global_geo: dict[str, Any] = {
                "floor_id": floor_id,
                "gx_ft": round(tx + x * ft_x, 3),
                "gy_ft": round(ty + y * ft_y, 3),
            }
            if geo.get("bx1") is not None and geo.get("by1") is not None:
                global_geo["gx1_ft"] = round(tx + geo["bx1"] * ft_x, 3)
                global_geo["gy1_ft"] = round(ty + geo["by1"] * ft_y, 3)
            if geo.get("bx2") is not None and geo.get("by2") is not None:
                global_geo["gx2_ft"] = round(tx + geo["bx2"] * ft_x, 3)
                global_geo["gy2_ft"] = round(ty + geo["by2"] * ft_y, 3)
            geo["global"] = global_geo
            all_pending[m["id"]] = {"geometry": geo}

    from app.services.database import bulk_update_by_id
    written = bulk_update_by_id("members", all_pending)
    return {"written": written, "pages": total_pages}


# ---------------------------------------------------------------------------
# Global Column Database
# ---------------------------------------------------------------------------
#
# Columns used to be re-derived every time /model/merged ran, by scanning
# every floor's pages for kind=="column" members and drawing one segment per
# floor iteration. That's wrong on two counts, confirmed by inspecting the
# real SteelGenie app directly (2026-07-14):
#
#   1. A physical column is a single real-world object with one X/Z location.
#      It should exist as exactly one row, extracted once from wherever its
#      location/mark is actually drawn (the foundation/column plan) -- not
#      re-created independently every time a page happens to reference it.
#      (classify_member()'s column_symbols gate, added earlier, already stops
#      beam/framing pages from manufacturing NEW column members; this table
#      is the other half: collapsing whatever column members legitimately do
#      exist, project-wide, into one row per physical column.)
#   2. A column's true height isn't its extraction page's own floor
#      elevation -- SteelGenie's Column Scheduler shows columns continuing
#      through multiple levels (Foundation -> Low Roof -> High Roof) with a
#      splice where the profile changes, and some columns stop early (only
#      reach Low Roof, never appear at High Roof). The real signal for how
#      tall a column actually is is which levels its beams actually frame
#      into it at -- if a beam on the High Roof plan ends right at a
#      column's (x,z), that's direct proof the column continues up to that
#      level, independent of which single page the column itself was drawn
#      on. This doesn't require OCR'ing the Column Schedule table (a
#      separate, tabular page -- S0400 in the reference project -- that
#      supplies the per-segment PROFILE and base plate/anchor info; that's
#      flagged as a follow-up once a real project PDF is available to
#      validate a table parser against).
COLUMN_SNAP_TOL_FT = 1.5  # project-wide XZ tolerance for "same physical column"

# 2026-07-17: live-verified on a real multi-sheet project (foundation +
# 2 framing plans of the same building) that inter-sheet registration noise
# routinely lands the SAME physical column 2-6ft apart in global XZ across
# different sheets -- well outside COLUMN_SNAP_TOL_FT's tight 1.5ft radius,
# so each sheet's detection of that one real column was silently becoming
# its own separate "column" row instead of merging (52 such near-duplicate
# pairs measured on that project via the /debug/column-segments endpoint).
# Simply widening COLUMN_SNAP_TOL_FT itself isn't safe: the pairwise-
# distance histogram on that same project has no clean gap between
# "registration noise" and "two real adjacent columns" -- distances from
# 1ft to 14ft are all populated, so a bigger single radius would start
# merging genuinely distinct columns in tight bays. grid_ref agreement is
# the disambiguating signal a real engineer would use here (same grid
# intersection = same physical column, regardless of per-sheet pixel
# noise) -- used ONLY as a secondary merge criterion within this wider-but-
# still-bounded radius, never as the sole identity, per the standing
# instruction that XZ proximity must stay authoritative (see the B1 comment
# below). Kept well under typical bay spacing (this project's grids run
# 21'-0" o.c.) so it only closes the specific gap it was measured to cause.
COLUMN_GRID_MERGE_TOL_FT = 8.0


def _build_column_segments(
    *, column_id: str, project_id: str, base_elev: float, top_elev: float,
    confirmed_top_elev: float, all_floor_elevs_sorted: list[float],
    profile: str | None,
) -> list[dict]:
    """
    Decompose one column's [base_elev, top_elev] extent into the real data
    model a structural column actually has: a STACK of floor-to-floor
    segments, not one base/top pair. Verified against the live SteelGenie
    reference app's Column Scheduler (2026-07-17 behavioral study) -- a
    real column there is shown as N segments, one per floor-to-floor span,
    each with its own profile, an explicit height, and a resolution
    source/review flag rather than one silent number.

    confirmed_top_elev: the highest elevation actual beam/joist evidence
    proves this column reaches (may equal base_elev if there's none at
    all). top_elev may be HIGHER than this -- sync_global_columns' Fix 2
    fallback extends a zero-evidence column to the next registered floor
    instead of leaving it at zero height, matching SteelGenie's own
    behavior (a locked "AUTO" segment with a warning icon, never a blank
    column). Every segment at or below confirmed_top_elev is genuinely
    beam-confirmed; every segment above it is inferred and always flagged
    for review here -- this is what lets that fallback stay honest instead
    of quietly pretending to be real evidence.

    What this deliberately does NOT yet do -- per-span profile splice
    detection (a column changing section partway up, which the live study
    confirmed real projects do) -- requires evidence this codebase doesn't
    extract yet (which page/extraction each span's profile comes from).
    Every segment below is written with the SAME profile (the column's own
    canonical profile). Splice detection is a separate, later phase.

    Purely additive to the CALLER's other behavior: does not change how
    base_elev_ft/top_elev_ft on the `columns` row are computed (that's
    sync_global_columns' job) -- this function only decides how to slice
    whatever [base_elev, top_elev] it's given into segment rows.
    """
    if top_elev <= base_elev:
        # No evidence this column reaches any floor above its base, and no
        # higher registered floor existed for the Fix 2 fallback to reach
        # either (e.g. this is the topmost floor in the project) -- one
        # zero-height segment, explicitly flagged for review rather than
        # silently omitted. Matches the "nothing fails silently" principle
        # from the diagnostics work earlier this project.
        return [{
            "id": str(uuid.uuid4()),
            "column_id": column_id,
            "project_id": project_id,
            "elev_bottom_ft": round(base_elev, 3),
            "elev_top_ft": round(base_elev, 3),
            "profile": profile,
            "resolution_source": "none",
            "is_locked": False,
            "review_flag": True,
            "review_reason": (
                "No beam/joist evidence connects this column to any floor "
                "above its base, and no higher floor is registered in this "
                "project for it to reach -- height could not be resolved."
            ),
        }]

    # Floors strictly between base and top, in order, define the segment
    # boundaries -- each floor-to-floor span becomes its own segment.
    span_elevs = [base_elev] + [
        e for e in all_floor_elevs_sorted if base_elev < e < top_elev
    ] + [top_elev]
    # De-dupe in case a floor elevation coincides with base/top exactly.
    span_elevs = sorted(set(span_elevs))

    segments = []
    for i in range(len(span_elevs) - 1):
        seg_bottom, seg_top = span_elevs[i], span_elevs[i + 1]
        # A segment is beam-confirmed only if its own top boundary is at or
        # below what beam/joist evidence actually proved -- not just "is
        # this the last segment", since the Fix 2 fallback can now push
        # top_elev past confirmed_top_elev entirely (in which case NONE of
        # the segments are confirmed, not just the earlier ones).
        is_confirmed = seg_top <= confirmed_top_elev + 1e-6
        source = "beam_connectivity" if is_confirmed else "floor_registration"
        segments.append({
            "id": str(uuid.uuid4()),
            "column_id": column_id,
            "project_id": project_id,
            "elev_bottom_ft": round(seg_bottom, 3),
            "elev_top_ft": round(seg_top, 3),
            "profile": profile,
            "resolution_source": source,
            "is_locked": False,
            "review_flag": not is_confirmed,
            "review_reason": (
                None if is_confirmed else
                "Inferred -- no beam/joist evidence confirms this column "
                "reaches this elevation; extended to the next floor "
                "registered in this project rather than left at zero "
                "height (see resolution_source)."
            ),
        })
    return segments


def sync_global_columns(project_id: str) -> dict:
    """Rebuild the `columns` table (the Global Column Database) for a
    project: one row per physical column, deduplicated by real-world (X, Z)
    position across every page/floor, with its true top elevation inferred
    from the highest floor whose beams actually connect to it.

    Idempotent and safe to call after every registration pass (see
    _ensure_project_registered in model.py) -- always fully replaces the
    project's columns rows from current member data rather than trying to
    incrementally patch them, since a single register_floor() re-run can
    change which members are duplicates/canonical.
    """
    db = get_db()

    drawings = db.table("drawings").select("id").eq("project_id", str(project_id)).execute().data or []
    drawing_ids = [d["id"] for d in drawings]
    if not drawing_ids:
        return {"columns": 0}
    pages = db.table("pages").select("*").in_("drawing_id", drawing_ids).execute().data or []
    if not pages:
        return {"columns": 0}
    pages_by_id = {p["id"]: p for p in pages}

    links = db.table("page_floor_links").select("*").execute().data or []
    floor_id_by_page = {l["page_id"]: l["floor_id"] for l in links}
    floors = db.table("floors").select("*").eq("project_id", str(project_id)).execute().data or []
    floor_elev_by_id = {f["id"]: f.get("elevation_ft") for f in floors}

    page_ids = list(pages_by_id.keys())
    all_members = db.table("members").select("*").in_("page_id", page_ids).neq("status", "excluded").execute().data or []

    # Phase 4 of the Column Engine: merge Column Schedule engineering data
    # (real profile, base plate, anchor rods, remarks) in by mark. See
    # app/engineering/column_schedule.py for the parser and
    # docs/column-engine-architecture.md section 2.3 for why this is a
    # separate pass rather than part of the plan-drawing member extraction.
    schedule_records = _collect_schedule_records(list(pages_by_id.values()), db)
    schedule_by_mark: dict[str, Any] = {}
    schedule_by_profile: dict[str, Any] = {}
    for rec in schedule_records:
        if rec.mark:
            schedule_by_mark.setdefault(rec.mark.strip().upper(), rec)
        elif rec.column_type or rec.profile:
            key = (rec.column_type or rec.profile).strip().upper()
            schedule_by_profile.setdefault(key, rec)
    if schedule_records:
        logger.info("Column schedule: parsed %d record(s) (%d by mark, %d by profile/type)",
                    len(schedule_records), len(schedule_by_mark), len(schedule_by_profile))

    # Split into column-type members (candidates for the Global Column
    # Database itself) and every OTHER member (used only as evidence of
    # "something connects here, so the column reaches at least this floor").
    column_members = []  # (m, gx, gz, floor_elev, grid_ref, is_foundation_plan)
    other_endpoints: list[tuple[float, float, float]] = []  # (gx, gz, floor_elev)
    for m in all_members:
        page = pages_by_id.get(m["page_id"])
        if not page:
            continue
        floor_id = floor_id_by_page.get(m["page_id"])
        floor_elev = floor_elev_by_id.get(floor_id) if floor_id else page.get("tos_ft")
        if floor_elev is None:
            continue
        g = member_global_endpoints(m, page, db)
        if m.get("kind") == "column":
            gx, gz = g.get("gx_ft"), g.get("gy_ft")
            if gx is None or gz is None:
                continue
            grid_ref = (m.get("geometry") or {}).get("grid_ref")
            # Stage 2 (2026-07-17 rebuild, live-verified): SteelGenie never
            # trusts a column detected off a framing/roof plan as its own
            # canonical identity -- it's held "Need Review" until reconciled
            # against the foundation-plan record for that same location.
            # bool(...) so a page whose is_foundation_plan is still None
            # (extracted before Fix 1 added the field) is conservatively
            # treated as NOT foundation-sourced rather than silently trusted.
            is_fp = bool(page.get("is_foundation_plan"))
            column_members.append((m, gx, gz, floor_elev, grid_ref, is_fp))
        else:
            for gx, gz in ((g.get("gx1_ft"), g.get("gy1_ft")), (g.get("gx2_ft"), g.get("gy2_ft"))):
                if gx is not None and gz is not None:
                    other_endpoints.append((gx, gz, floor_elev))

    # Group column-type members into one physical column per XZ cluster,
    # project-wide (not per-floor -- the same column extracted off the
    # foundation plan is one cluster regardless of how many floors exist).
    #
    # Position anchoring (2026-07-21 fix): a cluster used to report its
    # position as the running average of EVERY member's XZ, foundation-plan
    # and framing-plan alike. A structural column is a single physical
    # object with one true (X, Z) -- and the foundation plan is where it's
    # actually founded, so it's the authoritative source for that position,
    # exactly like SteelGenie (verified: framing/roof-plan columns are held
    # "Need Review" until reconciled against the foundation-plan record --
    # see the is_fp comment below). Blending in a framing-plan sheet's own
    # (possibly mis-registered, per-sheet-scale, or just less precise)
    # detection pulled the reported position away from where the column is
    # actually founded -- which is exactly the "column placed in the wrong
    # spot on the framing plan" symptom reported live. Fix: track a
    # SEPARATE running average over foundation-plan-sourced hits only
    # (gx_fp/gz_fp/n_fp); once any exist, _anchor_xz() below returns that
    # instead of the blended gx/gz. gx/gz themselves are left as the plain
    # all-member blend -- still used for cluster matching/merging, which is
    # a reasonable signal regardless of source -- only the REPORTED position
    # (evidence lookups + the row actually written to the columns table,
    # i.e. where every page/floor places this column) is anchored.
    clusters: list[dict] = []
    for m, gx, gz, floor_elev, grid_ref, is_fp in column_members:
        target = None
        for c in clusters:
            if math.hypot(gx - c["gx"], gz - c["gz"]) <= COLUMN_SNAP_TOL_FT:
                target = c
                break
        if target is None:
            target = {
                "gx": gx, "gz": gz, "members": [], "grid_votes": {},
                "has_foundation_source": False,
                "gx_fp": 0.0, "gz_fp": 0.0, "n_fp": 0,
            }
            clusters.append(target)
        target["members"].append((m, floor_elev))
        if is_fp:
            target["has_foundation_source"] = True
            target["n_fp"] += 1
            target["gx_fp"] += (gx - target["gx_fp"]) / target["n_fp"]
            target["gz_fp"] += (gz - target["gz_fp"]) / target["n_fp"]
        if grid_ref:
            target["grid_votes"][grid_ref] = target["grid_votes"].get(grid_ref, 0) + 1
        # Recenter the cluster on the running average position so a chain of
        # slightly-offset duplicate detections doesn't drift the anchor.
        n = len(target["members"])
        target["gx"] += (gx - target["gx"]) / n
        target["gz"] += (gz - target["gz"]) / n

    # B1 (column-engine-gap-analysis.md): the same physical-column cluster
    # can carry grid_ref from more than one page extraction. If they don't
    # all agree, that disagreement is itself a validation signal an XZ-only
    # clustering pass can't see -- surface the majority vote as the
    # cluster's grid_ref and flag the split as evidence of an uncertain
    # cluster boundary (logged, not hard-rejected -- XZ proximity is still
    # the authoritative clustering signal per the user's explicit
    # instruction not to make grid position the sole identity).
    def _recompute_grid_ref(c: dict) -> None:
        votes = c.get("grid_votes") or {}
        if votes:
            best_grid, best_count = max(votes.items(), key=lambda kv: kv[1])
            c["grid_ref"] = best_grid
            c["grid_conflict"] = len(votes) > 1 and best_count < sum(votes.values())
        else:
            c["grid_ref"] = None
            c["grid_conflict"] = False

    def _anchor_xz(c: dict) -> tuple[float, float]:
        """This cluster's authoritative real-world (X, Z) -- the
        foundation-plan position when one exists (see the "Position
        anchoring" comment above), otherwise the all-member blended
        centroid. Every place that reports or matches against "where this
        column is" should go through this, not read c['gx']/c['gz']
        directly, so the foundation plan stays the single source of truth
        for column placement across every sheet."""
        if c.get("n_fp", 0) > 0:
            return c["gx_fp"], c["gz_fp"]
        return c["gx"], c["gz"]

    for c in clusters:
        _recompute_grid_ref(c)

    # Second merge pass (2026-07-17, see COLUMN_GRID_MERGE_TOL_FT above):
    # two clusters that XZ-proximity alone left separate are still merged
    # if they (a) sit within a wider-but-bounded radius of each other AND
    # (b) agree on grid_ref -- catching the specific inter-sheet
    # registration-noise duplicate case without touching genuinely distinct
    # nearby columns, which won't share a grid_ref. Repeats until stable
    # since a merge can bring a third cluster's centroid into range.
    # Bug fix (2026-07-20, live-verified against "sasa"/Bayhealth: this pass
    # was throwing "list index out of range" and aborting sync_global_columns
    # entirely -- silently zeroing out the ENTIRE Global Column Database for
    # the whole project, not just skipping this merge step, because the
    # exception propagated out of the for-loop with nothing insertd yet).
    # Root cause: `for i in range(len(clusters))` fixes the loop bound at
    # the ORIGINAL list length, but `del clusters[j]` shrinks the list
    # mid-pass, so a later `i` from that same fixed range runs past the new
    # end of the list. Fix: break out of both loops the moment a merge
    # happens and let the outer `while merged_any` restart the pass fresh
    # against the new (shorter) list -- same eventual result ("repeats
    # until stable", per the comment above), just safe against mutation.
    merged_any = True
    while merged_any:
        merged_any = False
        for i in range(len(clusters)):
            ci = clusters[i]
            if ci.get("grid_ref") is None:
                continue
            for j in range(len(clusters) - 1, i, -1):
                cj = clusters[j]
                if cj.get("grid_ref") != ci.get("grid_ref"):
                    continue
                if math.hypot(*(a - b for a, b in zip(_anchor_xz(ci), _anchor_xz(cj)))) > COLUMN_GRID_MERGE_TOL_FT:
                    continue
                # Merge cj into ci: weighted-average centroid, union members,
                # combine grid votes, OR the foundation-source flag, and
                # combine the foundation-only accumulator the same way so
                # _anchor_xz keeps returning the true foundation-plan
                # position after the merge instead of losing it.
                n_i, n_j = len(ci["members"]), len(cj["members"])
                total = n_i + n_j
                ci["gx"] = (ci["gx"] * n_i + cj["gx"] * n_j) / total
                ci["gz"] = (ci["gz"] * n_i + cj["gz"] * n_j) / total
                n_fp_i, n_fp_j = ci.get("n_fp", 0), cj.get("n_fp", 0)
                total_fp = n_fp_i + n_fp_j
                if total_fp > 0:
                    ci["gx_fp"] = (ci.get("gx_fp", 0.0) * n_fp_i + cj.get("gx_fp", 0.0) * n_fp_j) / total_fp
                    ci["gz_fp"] = (ci.get("gz_fp", 0.0) * n_fp_i + cj.get("gz_fp", 0.0) * n_fp_j) / total_fp
                ci["n_fp"] = total_fp
                ci["members"].extend(cj["members"])
                ci["has_foundation_source"] = ci["has_foundation_source"] or cj["has_foundation_source"]
                for g, cnt in (cj.get("grid_votes") or {}).items():
                    ci["grid_votes"][g] = ci["grid_votes"].get(g, 0) + cnt
                _recompute_grid_ref(ci)
                del clusters[j]
                merged_any = True
                break
            if merged_any:
                break

    # Empirical mark -> grid_ref corroboration, built from every cluster in
    # this project that has BOTH a clean mark and a grid_ref -- lets a
    # schedule record's mark be checked against how that mark's grid
    # position actually behaves elsewhere on this same project, not just
    # matched by text equality. See column_match_engine.py for why.
    _canonical_marks_for_corroboration = []
    for c in clusters:
        if not c.get("grid_ref"):
            continue
        _members_sorted = sorted(
            c["members"],
            key=lambda t: (bool(((t[0].get("geometry") or {}).get("unlabeled"))), -(t[0].get("confidence") or 0)),
        )
        _canon = _members_sorted[0][0]
        _canonical_marks_for_corroboration.append({"mark": _canon.get("piecemark"), "grid_ref": c["grid_ref"]})
    grid_corroboration = column_match_engine.build_grid_corroboration_map(_canonical_marks_for_corroboration)

    floor_name_to_elev: dict[str, float] = {
        f.get("name"): f.get("elevation_ft")
        for f in floors
        if f.get("name") and f.get("elevation_ft") is not None
    }
    # Every real, currently-registered floor elevation in this project,
    # sorted -- used below to decompose a column's [base_elev, top_elev]
    # span into per-floor segments. Purely derived from
    # cluster_pages_into_floors()'s own output.
    all_floor_elevs_sorted = sorted({
        f.get("elevation_ft") for f in floors if f.get("elevation_ft") is not None
    })

    db.table("columns").delete().eq("project_id", str(project_id)).execute()
    db.table("column_segments").delete().eq("project_id", str(project_id)).execute()

    written = 0
    rejected_low_confidence = 0
    columns_to_insert = []
    segments_to_insert = []
    pending_ghost_updates: dict[str, dict] = {}
    for c in clusters:
        members = c["members"]
        # Base = the lowest floor this column's own extraction appears on
        # (its foundation/anchor level). Prefer a labeled member over an
        # unlabeled guess, then whichever extraction has the higher
        # confidence, as the canonical source for mark/profile/symbol.
        members.sort(key=lambda t: (
            bool(((t[0].get("geometry") or {}).get("unlabeled"))),
            -(t[0].get("confidence") or 0),
        ))
        canonical, base_elev = members[0]
        base_elev = min(fe for _m, fe in members)

        geo = canonical.get("geometry") or {}
        plan_mark = canonical.get("piecemark")
        plan_profile = canonical.get("section")

        # Top = the highest floor elevation any OTHER member (beam/joist)
        # connects to at this column's XZ position, within snap tolerance.
        # Tested against the anchored (foundation-plan-first) position, not
        # the raw blend, so beam-evidence matching lines up with the same
        # true location every other consumer of this cluster now uses.
        anchor_x, anchor_z = _anchor_xz(c)
        top_elev = base_elev
        for gx, gz, floor_elev in other_endpoints:
            if floor_elev <= top_elev:
                continue
            if math.hypot(gx - anchor_x, gz - anchor_z) <= COLUMN_SNAP_TOL_FT:
                top_elev = floor_elev
        # confirmed_top_elev: exactly what beam/joist evidence alone proves,
        # kept separate from the fallback below so column_segments can label
        # honestly which part of the column is actually confirmed vs
        # inferred (see _build_column_segments).
        confirmed_top_elev = top_elev

        # Fallback (2026-07-17 rebuild, Fix 2 -- verified live against the
        # real SteelGenie app's Column Scheduler, which never leaves a
        # column at zero height: an unconfirmed segment still gets a real,
        # LOCKED "AUTO" height with a warning icon, not a blank/invisible
        # column). If no beam evidence exists at all, extend to the next
        # REAL floor already registered in this project's own floors table
        # -- not a guessed/hardcoded story height, matching this codebase's
        # existing "no default storey height" principle elsewhere. Always
        # surfaced as review_flag=True in column_segments below, exactly
        # like SteelGenie's warning icon -- visibly uncertain, never hidden.
        if top_elev <= base_elev:
            # Stage 6 Part 4 / Floating Column Fix: A column detected only on 
            # a framing plan physically rises FROM the floor below TO that 
            # sheet's elevation. We must anchor the base at the nearest LOWER
            # registered floor first, so it supports the floor it was found on.
            lower_floors = [e for e in all_floor_elevs_sorted if e < base_elev]
            if lower_floors:
                base_elev = max(lower_floors)
                confirmed_top_elev = base_elev
            else:
                # If there are no lower floors (e.g. it's on the foundation plan),
                # it must extend UPWARD to the next floor.
                higher_floors = [e for e in all_floor_elevs_sorted if e > base_elev]
                if higher_floors:
                    top_elev = min(higher_floors)

        # Merge in Column Schedule data. B1 (column-engine-gap-analysis.md):
        # rather than first-match-wins on mark then profile text equality,
        # score every plausible candidate record using grid intersection,
        # world position, drawing mark, schedule mark, floor elevation,
        # classifier confidence, and beam connectivity together, and take
        # the best-scoring one -- this is what actually catches an OCR'd or
        # inconsistent mark ("C5" misread as "CS") that a bare text-equality
        # lookup would either wrongly match or wrongly miss: the grid
        # corroboration signal (built from every OTHER confidently-matched
        # cluster on this same project) either backs up or contradicts the
        # text match independent of the OCR reading itself.
        sched, sched_match_kind, match_score, match_signals = column_match_engine.find_best_schedule_match(
            cluster_grid_ref=c.get("grid_ref"),
            cluster_mark=plan_mark,
            cluster_profile=plan_profile,
            cluster_base_elev=base_elev,
            cluster_top_elev=top_elev,
            cluster_classifier_confidence=canonical.get("confidence"),
            cluster_has_beam_evidence=(top_elev > base_elev),
            schedule_by_mark=schedule_by_mark,
            schedule_by_profile=schedule_by_profile,
            grid_corroboration=grid_corroboration,
            floor_name_to_elev=floor_name_to_elev,
        )
        if sched:
            row_match_debug = {"score": match_score, "signals": match_signals, "kind": sched_match_kind}
        else:
            row_match_debug = None

        row = {
            "id": str(uuid.uuid4()),
            "project_id": str(project_id),
            "mark": plan_mark,
            # Anchored (foundation-plan-first) position -- this is the exact
            # (X, Z) written to every page/floor's 3D placement for this
            # column (see model.py's building-scope column emission), so
            # anchoring here is what actually fixes "column placed in the
            # wrong spot on the framing plan": every sheet now reports the
            # same foundation-sourced position instead of its own,
            # potentially mis-registered, independent detection.
            "gx_ft": round(anchor_x, 3),
            "gy_ft": round(anchor_z, 3),  # plan-axis position; named gy_ft to match member geometry's convention
            "base_elev_ft": round(base_elev, 3),
            "top_elev_ft": round(top_elev, 3),
            "profile": plan_profile,
            "symbol": geo.get("symbol"),
            "rotation": canonical.get("rotation", 0),
            "status": canonical.get("status"),
            "source_member_id": canonical.get("id"),
            "source_page_id": canonical.get("page_id"),
            # B1: grid intersection as a matching signal (not sole identity)
            # -- see column_match_engine.py. grid_conflict flags that this
            # cluster's own source extractions disagreed on grid_ref, a
            # signal the XZ-only clustering pass can't see on its own.
            "grid_ref": c.get("grid_ref"),
            "grid_conflict": c.get("grid_conflict", False),
        }
        if row_match_debug:
            row["schedule_match_score"] = row_match_debug["score"]
            row["schedule_match_signals"] = row_match_debug["signals"]
        if sched:
            # Schedule profile is the authoritative engineering value --
            # prefer it over the plan-symbol guess when both exist.
            row["profile"] = sched.profile or sched.column_type or plan_profile
            row["base_plate_mark"] = sched.base_plate_mark
            row["base_plate_elevation"] = sched.base_plate_elevation
            row["anchor_rods"] = sched.anchor_rods or None
            row["plate_dims"] = sched.plate_dims or None
            row["weld_size"] = sched.weld_size
            row["material"] = sched.material
            row["floor_segment"] = sched.floor_segment
            row["remarks"] = sched.remarks
            row["schedule_match_kind"] = sched_match_kind
            row["schedule_source_page_idx"] = sched.source_page_idx

        # Phase 1 confidence scoring -- combines per-member extraction
        # confidence, schedule corroboration, beam connectivity, and how
        # many independent page extractions agree this column exists here.
        # See column_validation.compute_column_confidence for the full
        # signal breakdown.
        row["confidence"] = compute_column_confidence(
            canonical_member=canonical,
            schedule_match_kind=sched_match_kind,
            has_beam_evidence=(top_elev > base_elev),
            n_source_extractions=len(members),
        )

        # Phase 6 validation -- reject rows that fail basic structural
        # sanity (no world coordinate, impossible elevation, no identity)
        # instead of silently writing them into the database a renderer
        # will later trust unconditionally.
        problems = validate_column_row(row)
        if problems:
            row["status"] = "need_review"
            row["validation_flags"] = problems
            logger.warning("[VALIDATION] Column at (%.1f, %.1f) flagged: %s",
                           c["gx"], c["gz"], problems)

        # Stage 2 (2026-07-17 rebuild, live-verified against SteelGenie's
        # Column Scheduler): a column with NO foundation-plan source at all
        # -- every one of its extractions came from a framing/roof plan --
        # has no canonical identity to be confirmed against yet. SteelGenie
        # holds these as "Need Review" until a human (or a later foundation
        # extraction) reconciles them, rather than silently promoting a
        # framing-plan detection straight to "active" just because nothing
        # else happened to be nearby. This is deliberately status-only: it
        # does not exclude the row from the Global Column Database (unlike
        # the low-confidence rejection below) -- SteelGenie still shows
        # these columns, just flagged, exactly like a real "Columns (36) --
        # all Need Review" page. Full reconciliation UI (accept/merge
        # against a specific foundation-plan column) is a separate,
        # not-yet-built follow-up -- this only gets the flag itself right.
        has_foundation_source = c.get("has_foundation_source", False)
        if not has_foundation_source:
            row["status"] = "need_review"
            row["needs_foundation_reconciliation"] = True
            existing_flags = row.get("validation_flags") or []
            row["validation_flags"] = existing_flags + ["no_foundation_plan_source"]
            logger.info(
                "[STAGE2] Column at (%.1f, %.1f) has no foundation-plan source -- "
                "flagged need_review pending reconciliation.",
                c["gx"], c["gz"],
            )

        # Stage 6 Part 3 (2026-07-20, live-verified against the "sasa"/
        # Bayhealth project, page 15 "Framing Plan - Level 2"): a framing
        # page with no drawn column symbol at a grid intersection gets a
        # page-local ghost "suggested" placeholder (see analyse.py "Emit
        # Suggested Ghost Columns") so the review queue doesn't silently
        # drop that location. The 2D overlay deliberately renders that
        # ghost as a faint, near-invisible dashed ring BECAUSE it's
        # unconfirmed -- but this reconciliation pass, two lines above,
        # already knows project-wide whether a real foundation-plan
        # detection exists at this same physical (gx, gz). If it does, the
        # ghost isn't actually uncertain anymore: it's a real column whose
        # symbol just wasn't redrawn on this particular framing sheet,
        # which is normal -- framing plans usually don't re-draw column
        # icons and rely on the grid instead. Patch the underlying
        # page-level member rows so every plan the column appears on shows
        # it the same, confirmed way -- matching SteelGenie's one
        # consistent, correctly-placed column per physical location across
        # every drawing -- instead of only the aggregate Global Column
        # Database knowing this while each individual 2D sheet still shows
        # a barely-visible guess. General by construction: keys off the
        # same has_foundation_source signal used for the reconciliation
        # flag above, for every project, not any one drawing's text/format.
        if has_foundation_source:
            try:
                for gm, _fe in members:
                    ggeo = gm.get("geometry") or {}
                    if not ggeo.get("suggested"):
                        continue
                    new_geo = dict(ggeo)
                    new_geo["suggested"] = False
                    old_flags = new_geo.get("error_flags")
                    if not isinstance(old_flags, list):
                        old_flags = []
                    new_geo["error_flags"] = [f for f in old_flags if f != "missing"]
                    member_update: dict = {"geometry": new_geo}
                    # Backfill a real profile/mark onto the ghost's label only
                    # if the ghost itself never got one, from the foundation-
                    # sourced canonical member for this same physical column.
                    if not gm.get("section") and plan_profile:
                        member_update["section"] = plan_profile
                    if gm.get("id"):
                        pending_ghost_updates[gm["id"]] = member_update
            except Exception:
                # Defensive: this reconciliation pass must never be able to
                # abort the surrounding cluster loop -- the bulk columns
                # insert only happens after every cluster is processed, so
                # one bad member row here would otherwise silently wipe out
                # the entire Global Column Database for the whole project.
                logger.exception(
                    "Ghost-column reconciliation failed for cluster at (%.1f, %.1f) -- "
                    "skipping reconciliation for this cluster only.",
                    c["gx"], c["gz"],
                )

        # Column Validation Engine -- global-stage hard gate. Page-level
        # extraction (main.py: emit_symbol_columns) already runs the same
        # engine with the signals available at that point (grid, footing
        # classification, mark distance, beam connectivity); this is the
        # one signal it structurally CANNOT have yet -- Column Schedule
        # corroboration, since the schedule is parsed and matched here,
        # after every page in the project has been collected. A candidate
        # with essentially no identity (no mark, no profile) AND no
        # schedule match AND very low confidence has nothing left
        # distinguishing it from a stray annotation mark that slipped past
        # every earlier filter -- that combination is what gets excluded
        # from the Global Column Database entirely, rather than written
        # and merely flagged. Everything with SOME real evidence (a mark,
        # a profile, a schedule match, or reasonable confidence) still
        # gets written as need_review -- recoverable by a human, unlike a
        # false positive silently entering the database as fact.
        no_identity = "no_mark_no_profile" in problems
        no_schedule = sched_match_kind is None
        very_low_confidence = row["confidence"] < 0.20
        if no_identity and no_schedule and very_low_confidence:
            logger.warning(
                "[VALIDATION] Column at (%.1f, %.1f) REJECTED -- no mark/profile, "
                "no schedule match, confidence %.2f < 0.20: %s",
                c["gx"], c["gz"], row["confidence"], row,
            )
            try:
                db.table("validation_issues").insert({
                    "project_id": str(project_id),
                    "type": "column_rejected_low_confidence",
                    "severity": "warning",
                    "message": (
                        f"A column candidate at grid position ({c['gx']:.1f}, {c['gz']:.1f}) "
                        f"was excluded from the Global Column Database -- no mark, no profile, "
                        f"no Column Schedule match, and confidence {row['confidence']:.2f} "
                        f"(below the 0.20 floor). Likely a false positive that passed shape "
                        f"detection but has no independent structural corroboration."
                    ),
                    "gx_ft": round(c["gx"], 3),
                    "gy_ft": round(c["gz"], 3),
                }).execute()
            except Exception as exc:
                logger.warning("Could not persist rejected-column validation issue: %s", exc)
            rejected_low_confidence += 1
            continue

        columns_to_insert.append(row)
        written += 1

        # Phase 2 of the rebuild (docs: SteelGenie behavioral study,
        # 2026-07-17 chat) -- a column's real vertical extent is a STACK of
        # floor-to-floor segments, each independently sourced/profiled, not
        # one base/top pair. See app.engineering.registration module
        # docstring notes near COLUMN_SNAP_TOL_FT for the full rationale.
        # Additive only: base_elev_ft/top_elev_ft above are UNCHANGED and
        # still the source of truth for every existing caller (3D render,
        # BOM, etc) -- nothing reads column_segments yet. This just starts
        # populating the real data model so later phases (splice/profile
        # detection, the Column Scheduler-equivalent UI, render-from-
        # segments) have real rows to build against instead of starting
        # from an empty table.
        segments = _build_column_segments(
            column_id=row["id"], project_id=str(project_id),
            base_elev=base_elev, top_elev=top_elev,
            confirmed_top_elev=confirmed_top_elev,
            all_floor_elevs_sorted=all_floor_elevs_sorted,
            profile=row.get("profile"),
        )
        segments_to_insert.extend(segments)

    # Bulk insert columns and segments to prevent N disk writes in Mock DB
    if columns_to_insert:
        for i in range(0, len(columns_to_insert), 100):
            db.table("columns").insert(columns_to_insert[i:i+100]).execute()
    if segments_to_insert:
        for i in range(0, len(segments_to_insert), 100):
            db.table("column_segments").insert(segments_to_insert[i:i+100]).execute()
    if pending_ghost_updates:
        from app.services.database import bulk_update_by_id
        bulk_update_by_id("members", pending_ghost_updates)

    schedule_marks_found = len(schedule_by_mark) or len({
        (r.column_type or r.profile) for r in schedule_records
        if not r.mark and (r.column_type or r.profile)
    })
    check_schedule_count_anomaly(
        project_id, columns_written=written,
        schedule_marks_found=schedule_marks_found, db=db,
    )

    if rejected_low_confidence:
        logger.info("[VALIDATION] %d column candidate(s) excluded from the Global Column "
                    "Database (no mark/profile, no schedule match, confidence < 0.20)",
                    rejected_low_confidence)

    return {"columns": written, "schedule_records": len(schedule_records),
            "schedule_marks_found": schedule_marks_found,
            "rejected_low_confidence": rejected_low_confidence}


def debug_column_trace(project_id: str, sample_size: int = 5, focus_page_ids: list[str] | None = None) -> dict:
    """
    READ-ONLY diagnostic. Does not write anything to the database and does
    not change any production logic -- it re-derives the exact same
    base_elev/top_elev computation sync_global_columns() does, but keeps
    full evidence of every decision (which beam endpoints were considered,
    why each one was accepted or rejected) instead of collapsing it into a
    final number.

    Built specifically to answer, with real data instead of assumption,
    whether zero-height columns are caused by (a) floor registration being
    fragmented so beams and columns never share a floor_elev, (b) a
    coordinate mismatch between beam and column world positions, (c) the
    snap tolerance being too tight, or (d) beams for the relevant floor
    simply not existing yet in the members table. See
    docs/column-engine-architecture.md and the B1/gap-analysis docs for
    context -- this is intentionally a side-by-side function, not a
    refactor of sync_global_columns(), so it cannot itself change any
    already-working behavior.

    focus_page_ids: if given, the column sample is drawn preferentially
    from clusters whose canonical (best) member was extracted on one of
    these pages, falling back to the first N clusters overall if fewer
    than sample_size match. Lets a caller ask "show me columns from Page
    14/15 specifically" instead of an arbitrary sample that might all be
    single-page, single-floor stubs with nothing to prove either way.
    """
    db = get_db()

    drawings = db.table("drawings").select("*").eq("project_id", str(project_id)).execute().data or []
    drawing_ids = [d["id"] for d in drawings]
    if not drawing_ids:
        return {"error": "no drawings for project"}
    pages = db.table("pages").select("*").in_("drawing_id", drawing_ids).execute().data or []
    if not pages:
        return {"error": "no pages for project"}
    pages_by_id = {p["id"]: p for p in pages}
    pages_sorted = sorted(pages, key=lambda p: p.get("idx", 0))
    page_number_by_id = {p["id"]: (i + 1) for i, p in enumerate(pages_sorted)}  # 1-based, matches UI "Page N"

    links = db.table("page_floor_links").select("*").execute().data or []
    floor_id_by_page = {l["page_id"]: l["floor_id"] for l in links}
    floors = db.table("floors").select("*").eq("project_id", str(project_id)).execute().data or []
    floor_elev_by_id = {f["id"]: f.get("elevation_ft") for f in floors}
    floor_by_id = {f["id"]: f for f in floors}

    page_ids = list(pages_by_id.keys())
    all_members = db.table("members").select("*").in_("page_id", page_ids).neq("status", "excluded").execute().data or []

    # ── Floor registration report ───────────────────────────────────────────
    floor_report = []
    members_per_page: dict[str, int] = {}
    for m in all_members:
        members_per_page[m["page_id"]] = members_per_page.get(m["page_id"], 0) + 1
    for p in pages_sorted:
        pid = p["id"]
        fid = floor_id_by_page.get(pid)
        floor = floor_by_id.get(fid) if fid else None
        resolved_elev = floor_elev_by_id.get(fid) if fid else p.get("tos_ft")
        floor_report.append({
            "page_number": page_number_by_id[pid],
            "page_id": pid,
            "sheet_label": p.get("label") or p.get("sheet_number") or None,
            "input_tos_ft": p.get("tos_ft"),
            "registered_floor_id": fid,
            "registered_floor_name": floor.get("name") if floor else None,
            "registered_floor_elevation_ft": floor.get("elevation_ft") if floor else None,
            "resolved_floor_elev_used_by_sync": resolved_elev,
            "has_floor_link": fid is not None,
            "members_on_page": members_per_page.get(pid, 0),
        })

    # ── Rebuild column_members / other_endpoints EXACTLY like
    #    sync_global_columns(), but keep per-item provenance ─────────────────
    column_members = []  # (m, gx, gz, floor_elev, grid_ref, page_id, floor_id)
    other_endpoints = []  # (gx, gz, floor_elev, member_id, page_id, floor_id, piecemark, kind)
    skipped_no_floor_elev = 0
    for m in all_members:
        page = pages_by_id.get(m["page_id"])
        if not page:
            continue
        floor_id = floor_id_by_page.get(m["page_id"])
        floor_elev = floor_elev_by_id.get(floor_id) if floor_id else page.get("tos_ft")
        if floor_elev is None:
            skipped_no_floor_elev += 1
            continue
        g = member_global_endpoints(m, page, db)
        if m.get("kind") == "column":
            gx, gz = g.get("gx_ft"), g.get("gy_ft")
            if gx is None or gz is None:
                continue
            grid_ref = (m.get("geometry") or {}).get("grid_ref")
            column_members.append((m, gx, gz, floor_elev, grid_ref, m["page_id"], floor_id))
        else:
            for gx, gz in ((g.get("gx1_ft"), g.get("gy1_ft")), (g.get("gx2_ft"), g.get("gy2_ft"))):
                if gx is not None and gz is not None:
                    other_endpoints.append((gx, gz, floor_elev, m.get("id"), m["page_id"], floor_id,
                                             m.get("piecemark"), m.get("kind")))

    clusters: list[dict] = []
    for m, gx, gz, floor_elev, grid_ref, page_id, floor_id in column_members:
        target = None
        for c in clusters:
            if math.hypot(gx - c["gx"], gz - c["gz"]) <= COLUMN_SNAP_TOL_FT:
                target = c
                break
        if target is None:
            target = {"gx": gx, "gz": gz, "members": []}
            clusters.append(target)
        target["members"].append((m, floor_elev, page_id, floor_id))
        n = len(target["members"])
        target["gx"] += (gx - target["gx"]) / n
        target["gz"] += (gz - target["gz"]) / n

    # ── Pick the sample: prefer clusters touching focus_page_ids ────────────
    def _cluster_page_ids(c: dict) -> set:
        return {pid for (_m, _fe, pid, _fid) in c["members"]}

    ordered = list(clusters)
    if focus_page_ids:
        focus_set = set(focus_page_ids)
        ordered.sort(key=lambda c: 0 if (_cluster_page_ids(c) & focus_set) else 1)
    sample = ordered[:sample_size]

    trace = []
    for idx, c in enumerate(sample):
        members = c["members"]
        members_sorted = sorted(members, key=lambda t: (
            bool(((t[0].get("geometry") or {}).get("unlabeled"))),
            -(t[0].get("confidence") or 0),
        ))
        canonical, _base_elev0, canon_page_id, canon_floor_id = members_sorted[0]
        base_elev = min(fe for _m, fe, _pid, _fid in members)

        beam_search_log = []
        top_elev = base_elev
        for gx, gz, floor_elev, member_id, page_id, floor_id, piecemark, kind in other_endpoints:
            dist = math.hypot(gx - c["gx"], gz - c["gz"])
            reasons = []
            accepted = True
            if floor_elev <= base_elev:
                accepted = False
                reasons.append(f"elevation {floor_elev}' not above base {base_elev}'")
            if dist > COLUMN_SNAP_TOL_FT:
                accepted = False
                reasons.append(f"distance {dist:.2f}ft exceeds tolerance {COLUMN_SNAP_TOL_FT}ft")
            if accepted:
                beam_search_log.append({
                    "member_id": member_id, "page_id": page_id, "page_number": page_number_by_id.get(page_id),
                    "kind": kind, "piecemark": piecemark, "distance_ft": round(dist, 3),
                    "floor_elev": floor_elev, "result": "ACCEPTED",
                })
                if floor_elev > top_elev:
                    top_elev = floor_elev
            elif dist <= COLUMN_SNAP_TOL_FT * 4:
                # Only log near-misses (within 4x tolerance) -- logging every
                # rejected beam on the whole project would be thousands of
                # irrelevant rows for a column that's nowhere near them.
                beam_search_log.append({
                    "member_id": member_id, "page_id": page_id, "page_number": page_number_by_id.get(page_id),
                    "kind": kind, "piecemark": piecemark, "distance_ft": round(dist, 3),
                    "floor_elev": floor_elev, "result": "REJECTED", "reasons": reasons,
                })

        top_elev = max(top_elev, max(fe for _m, fe, _pid, _fid in members))
        connected = [b for b in beam_search_log if b["result"] == "ACCEPTED"]

        if not connected:
            if not beam_search_log:
                fail_reason = (
                    f"No beam/joist endpoints exist anywhere within {COLUMN_SNAP_TOL_FT * 4}ft of this "
                    f"column's world position ({c['gx']:.2f}, {c['gz']:.2f}) on any floor above {base_elev}'. "
                    f"Either no framing plan above this column has been extracted yet, or its world "
                    f"coordinates don't line up with this column's."
                )
            else:
                worst = beam_search_log[0]["reasons"]
                fail_reason = f"Nearby beam(s) found but rejected: {worst[0] if worst else 'unknown'}"
        else:
            fail_reason = None

        trace.append({
            "column_index": idx,
            "grid_ref": (canonical.get("geometry") or {}).get("grid_ref"),
            "canonical_page_number": page_number_by_id.get(canon_page_id),
            "canonical_page_id": canon_page_id,
            "canonical_floor_id": canon_floor_id,
            "piecemark": canonical.get("piecemark"),
            "profile": canonical.get("section"),
            "world_x_ft": round(c["gx"], 3),
            "world_z_ft": round(c["gz"], 3),
            "base_elev_ft": base_elev,
            "top_elev_ft": top_elev,
            "height_ft": round(top_elev - base_elev, 3),
            "n_source_pages": len({pid for _m, _fe, pid, _fid in members}),
            "connected_beam_count": len(connected),
            "connected_beam_ids": [b["member_id"] for b in connected],
            "beam_search_log": beam_search_log,
            "result": "OK" if top_elev > base_elev else "FAILED",
            "fail_reason": fail_reason,
        })

    return {
        "project_id": str(project_id),
        "total_pages": len(pages),
        "total_members": len(all_members),
        "total_column_members": len(column_members),
        "total_other_endpoints": len(other_endpoints),
        "total_clusters": len(clusters),
        "skipped_no_floor_elev": skipped_no_floor_elev,
        "column_snap_tol_ft": COLUMN_SNAP_TOL_FT,
        "floor_report": floor_report,
        "sample_trace": trace,
    }
