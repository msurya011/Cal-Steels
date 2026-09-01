"""
Supabase client helpers — thin wrappers around the supabase-py client.
Includes a fully compliant local offline Mock DB engine when Supabase is unresolvable.
"""
from __future__ import annotations

import glob
import logging
import os
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

from supabase import Client, create_client
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[Any] = None

# Guards every read-modify-write cycle against this mock DB (load -> mutate
# -> save), process-wide. Originally _save_db() alone had an atomic-rename
# write (temp file + os.replace), which is enough to stop a SINGLE writer
# from ever leaving a half-written file on disk -- but it does nothing once
# there are multiple concurrent writers, which became a real scenario this
# session (register_floor() now runs on background executor threads from
# several endpoints/jobs, sometimes overlapping). Two threads both writing
# to the SAME fixed tmp path ("local_db.json.tmp") at once can interleave
# their writes at the OS level (both file descriptors point at the same
# inode), producing a file that's neither writer's clean output -- exactly
# the "valid JSON followed by extra garbage data" corruption seen in
# practice. Separately, _db_cache is a single shared dict mutated in place;
# without a lock spanning the full load->mutate->save cycle, two threads'
# writes can also just clobber/lose each other's changes even if the file
# itself stays syntactically valid ("lost update"). A single re-entrant
# lock around every mutating operation's full cycle fixes both.
_db_lock = threading.RLock()

# Local database file path
_DB_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "local_db.json"
)

# Clean up orphaned .tmp files left by past crashed writes.
# Each crash creates a <pid>.<tid>.tmp file that never gets removed, and they
# accumulate on disk. This runs once at import time (server startup) and is
# a no-op when there are no stale files to remove.
def _cleanup_tmp_files() -> None:
    for _tmp in glob.glob(f"{_DB_FILE}.*.tmp"):
        try:
            os.remove(_tmp)
            logger.debug("Removed orphaned tmp file: %s", _tmp)
        except OSError:
            pass

_cleanup_tmp_files()

# In-process cache of the parsed DB, keyed off the file's mtime. Every single
# .execute() call in MockQueryBuilder used to call _load_db(), which did a
# fresh json.load() of the WHOLE file every time -- fine when this file was
# small, but it has since grown to tens of thousands of records (members,
# grids, bom_items...). Endpoints that chain many .execute() calls in a loop
# (floor clustering, page registration, model assembly -- easily 50-100+
# calls in one request) were re-parsing the entire multi-MB file on every
# single one of those calls, synchronously blocking the event loop long
# enough that the frontend saw the request as permanently hung rather than
# just slow. Caching the parsed dict and only re-reading when the file has
# actually changed on disk (checked via mtime, so external edits -- e.g. a
# human hand-editing local_db.json while the server runs -- still get
# picked up) turns most calls into an in-memory lookup instead.
_db_cache: Optional[dict] = None
_db_cache_mtime: Optional[float] = None

# Lazy (table, field) -> {value: [rows]} index for the single-eq-filter case,
# which is the overwhelming majority of queries in this codebase
# (.eq("page_id", ...), .eq("floor_id", ...), .eq("id", ...), etc). Without
# this, every one of those calls did a full O(table_size) Python-level scan
# via _matches() -- and code paths like register_floor()/
# cluster_pages_into_floors() call .eq(...).execute() dozens of times in
# nested per-page, per-floor loops against tables (members, grids, pages)
# that hold every project's data, not just the one being viewed. That's
# O(floors x pages x table_size), which is what turned "load a project" into
# a multi-second-to-indefinite hang as the tables grew. Invalidated (cleared)
# any time the underlying data can have changed -- see _load_db()/_save_db().
_index_cache: dict[tuple[str, str], dict[str, list[dict]]] = {}


def _invalidate_indexes() -> None:
    _index_cache.clear()


def _get_table_index(table_name: str, field: str, items: list[dict]) -> dict[str, list[dict]]:
    idx_key = (table_name, field)
    index = _index_cache.get(idx_key)
    if index is None:
        index = {}
        for item in items:
            iv = str(item.get(field)) if item.get(field) is not None else "null"
            index.setdefault(iv, []).append(item)
        _index_cache[idx_key] = index
    return index


def _candidates(table_name: str, items: list[dict], filters: list[tuple[str, str, Any]]) -> list[dict]:
    """Return the candidate rows to check for a query, using the (table, field) index
    when an eq() or in_() filter is available, otherwise the full table."""
    if not filters or not items:
        return items

    # Look for the best indexed filter among the query filters
    for field, op, val in filters:
        if op == "eq":
            index = _get_table_index(table_name, field, items)
            return index.get(val, [])
        elif op == "in" and isinstance(val, (list, set, tuple)):
            index = _get_table_index(table_name, field, items)
            candidates = []
            seen_ids = set()
            for v in val:
                for row in index.get(str(v), []):
                    row_id = id(row)
                    if row_id not in seen_ids:
                        seen_ids.add(row_id)
                        candidates.append(row)
            return candidates

    return items


def _load_db() -> dict:
    global _db_cache, _db_cache_mtime

    if os.path.exists(_DB_FILE):
        try:
            mtime = os.path.getmtime(_DB_FILE)
        except OSError:
            mtime = None
        if _db_cache is not None and mtime is not None and mtime == _db_cache_mtime:
            return _db_cache

    default_db = {
        "users": [],
        "projects": [],
        "drawings": [],
        "pages": [],
        "members": [],
        "jobs": [],
        "bom_items": [],
        "sections": [],
        "configurations": [],
        "notifications": [],
        "layer_presets": [],
        "column_groups": [],
        "braced_frames": [],
        "floors": [],
        "grids": [],
        "match_lines": [],
        "page_floor_links": [],
        "page_registrations": []
    }
    if not os.path.exists(_DB_FILE):
        db = default_db
    else:
        try:
            with open(_DB_FILE, "r") as f:
                db = json.load(f)
            _db_cache_mtime = os.path.getmtime(_DB_FILE)
        except Exception as e:
            # IMPORTANT: do not silently discard the file's contents here.
            # This used to be `except Exception: db = default_db`, which
            # means any corruption of local_db.json (e.g. trailing NUL
            # bytes from an editor/OS write glitch -- confirmed to happen
            # in this project) made every request quietly fall back to an
            # empty in-memory DB. The very next write then persisted that
            # empty DB back to disk, permanently erasing every real
            # project/member/floor that existed before the corruption.
            # Recover from the one corruption pattern we know how to fix
            # safely (trailing NUL padding after otherwise-valid JSON)
            # before ever falling back to an empty database, and log loudly
            # either way so this isn't invisible next time.
            recovered = False
            try:
                with open(_DB_FILE, "rb") as f:
                    raw = f.read()
                stripped = raw.rstrip(b"\x00")
                if stripped and stripped != raw:
                    db = json.loads(stripped.decode("utf-8"))
                    with open(_DB_FILE, "wb") as f:
                        f.write(stripped)
                    _db_cache_mtime = os.path.getmtime(_DB_FILE)
                    recovered = True
                    logger.warning(
                        "local_db.json had %d trailing NUL byte(s) after valid JSON -- "
                        "stripped and recovered %d project(s) instead of resetting to empty.",
                        len(raw) - len(stripped), len(db.get("projects", [])),
                    )
            except Exception:
                recovered = False
            if not recovered:
                logger.error(
                    "local_db.json is corrupt and could not be auto-recovered (%s). "
                    "Falling back to an empty in-memory DB -- if this gets saved, any "
                    "existing data in the file will be lost. Back up local_db.json now "
                    "and inspect it before making further requests.", e,
                )
                db = default_db
                _db_cache_mtime = None

    # Ensure all tables exist
    for key, val in default_db.items():
        if key not in db:
            db[key] = val

    # Seed sections library if empty
    if not db["sections"]:
        seeds = [
            {"designation": "W14X90", "standard": "AISC", "section_type": "W", "weight_per_ft": 90.0, "depth_in": 14.0, "flange_width_in": 14.5, "flange_thick_in": 0.71, "web_thick_in": 0.44, "cross_area_in2": 26.5},
            {"designation": "W14X68", "standard": "AISC", "section_type": "W", "weight_per_ft": 68.0, "depth_in": 14.0, "flange_width_in": 10.0, "flange_thick_in": 0.72, "web_thick_in": 0.41, "cross_area_in2": 20.0},
            {"designation": "W14X48", "standard": "AISC", "section_type": "W", "weight_per_ft": 48.0, "depth_in": 13.8, "flange_width_in": 8.0, "flange_thick_in": 0.59, "web_thick_in": 0.34, "cross_area_in2": 14.1},
            {"designation": "W12X96", "standard": "AISC", "section_type": "W", "weight_per_ft": 96.0, "depth_in": 12.7, "flange_width_in": 12.2, "flange_thick_in": 0.90, "web_thick_in": 0.55, "cross_area_in2": 28.2},
            {"designation": "W12X53", "standard": "AISC", "section_type": "W", "weight_per_ft": 53.0, "depth_in": 12.1, "flange_width_in": 10.0, "flange_thick_in": 0.57, "web_thick_in": 0.34, "cross_area_in2": 15.6},
            {"designation": "W12X26", "standard": "AISC", "section_type": "W", "weight_per_ft": 26.0, "depth_in": 12.2, "flange_width_in": 6.5, "flange_thick_in": 0.38, "web_thick_in": 0.23, "cross_area_in2": 7.65},
            {"designation": "W10X49", "standard": "AISC", "section_type": "W", "weight_per_ft": 49.0, "depth_in": 10.0, "flange_width_in": 10.0, "flange_thick_in": 0.56, "web_thick_in": 0.34, "cross_area_in2": 14.4},
            {"designation": "W10X30", "standard": "AISC", "section_type": "W", "weight_per_ft": 30.0, "depth_in": 10.5, "flange_width_in": 5.8, "flange_thick_in": 0.51, "web_thick_in": 0.30, "cross_area_in2": 8.84},
            {"designation": "W10X19", "standard": "AISC", "section_type": "W", "weight_per_ft": 19.0, "depth_in": 10.2, "flange_width_in": 4.0, "flange_thick_in": 0.39, "web_thick_in": 0.25, "cross_area_in2": 5.62},
            {"designation": "W8X31",  "standard": "AISC", "section_type": "W", "weight_per_ft": 31.0, "depth_in": 8.0, "flange_width_in": 8.0, "flange_thick_in": 0.43, "web_thick_in": 0.28, "cross_area_in2": 9.13},
            {"designation": "W8X15",  "standard": "AISC", "section_type": "W", "weight_per_ft": 15.0, "depth_in": 8.1, "flange_width_in": 4.0, "flange_thick_in": 0.31, "web_thick_in": 0.24, "cross_area_in2": 4.44},
            {"designation": "W6X9",   "standard": "AISC", "section_type": "W", "weight_per_ft": 9.0,  "depth_in": 5.9, "flange_width_in": 3.9, "flange_thick_in": 0.21, "web_thick_in": 0.17, "cross_area_in2": 2.68}
        ]
        db["sections"] = seeds
        _save_db(db)

    _db_cache = db
    _invalidate_indexes()
    return db


def _save_db(data: dict) -> None:
    global _db_cache, _db_cache_mtime
    try:
        # Write atomically: dump to a temp file in the same directory, then
        # os.replace() over the real path. A plain open(_DB_FILE, "w") +
        # json.dump() writes in place -- if the process is interrupted mid-
        # dump (dev-server hot-reload firing mid-request, a crash, or two
        # requests racing to write at once), local_db.json is left truncated
        # and every subsequent read of the ENTIRE database fails, not just
        # the one row being written. This happened for real: a request that
        # looped over hundreds of members calling .update().execute() once
        # each got cut off partway through and corrupted the whole file.
        # os.replace() is atomic on both POSIX and Windows, so readers only
        # ever see the fully-old or fully-new file, never a half-written one
        # -- AS LONG AS every writer uses its own tmp file. A fixed shared
        # name here meant two concurrent writers (now a real scenario, e.g.
        # register_floor() on background executor threads, or a dev-server
        # hot-reload starting a new process before the old one's write
        # finished) could both have the same inode open at once, and their
        # write() calls interleave at the OS level -- producing a tmp file
        # that's neither writer's clean output, which os.replace() then
        # atomically installs as the "valid" database. _db_lock (see above)
        # already serializes writers within this one process; making the
        # path unique per-writer closes the remaining cross-process gap too.
        tmp_path = f"{_DB_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        import time
        replaced = False
        for attempt in range(5):
            try:
                os.replace(tmp_path, _DB_FILE)
                replaced = True
                break
            except (PermissionError, OSError):
                time.sleep(0.05 * (attempt + 1))
        if not replaced:
            # Fallback if replace is still locked
            with open(_DB_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
        # Keep the cache in lockstep with what we just wrote, so the very
        # next _load_db() call (e.g. the next chained .execute() in the same
        # request) reuses this in-memory copy instead of re-reading the file
        # we just finished writing.
        _db_cache = data
        try:
            _db_cache_mtime = os.path.getmtime(_DB_FILE)
        except OSError:
            _db_cache_mtime = None
        # A write can add/remove/change rows in any table, so any index built
        # against the pre-write data is potentially stale. Rebuilding an
        # index is O(table_size) done once on next use -- still vastly
        # cheaper than the O(table_size) scan we were doing on every single
        # query before this cache existed.
        _invalidate_indexes()
    except Exception as exc:
        logger.error("Failed to write local offline DB: %s", exc)


class MockQueryBuilder:
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.filters: list[tuple[str, str, Any]] = []
        self.limit_val: Optional[int] = None
        self.offset_val: int = 0
        self.order_by: Optional[str] = None
        self.order_desc: bool = False
        self._single_flag: bool = False
        self._maybe_single_flag: bool = False

    def select(self, *args, **kwargs) -> MockQueryBuilder:
        return self

    def insert(self, data: Any) -> MockQueryBuilder:
        with _db_lock:
            db = _load_db()
            rows = data if isinstance(data, list) else [data]
            inserted = []
            for row in rows:
                row = dict(row)
                if "id" not in row:
                    row["id"] = str(uuid.uuid4())
                row["created_at"] = datetime.now(timezone.utc).isoformat()
                row["updated_at"] = datetime.now(timezone.utc).isoformat()
                db.setdefault(self.table_name, []).append(row)
                inserted.append(row)
            _save_db(db)
        self._result = inserted
        return self

    def update(self, data: Any) -> MockQueryBuilder:
        # IMPORTANT: this must NOT execute immediately. Every caller in this
        # codebase chains filters AFTER update(), e.g.
        #   db.table("pages").update({...}).eq("id", page_id).execute()
        # If update() ran here, self.filters would still be empty (the
        # .eq() call hasn't happened yet) and _matches() would match EVERY
        # row in the table -- silently overwriting the whole table instead
        # of the one intended row. Defer to execute() instead, by which
        # point all chained filters have been collected.
        self._pending_update = data
        return self

    def delete(self) -> MockQueryBuilder:
        # Same reasoning as update(): must defer to execute() so filters
        # chained after .delete() (the convention used everywhere in this
        # codebase) are honored instead of deleting every row in the table.
        self._pending_delete = True
        return self

    def eq(self, field: str, value: Any) -> MockQueryBuilder:
        self.filters.append((field, "eq", str(value)))
        return self

    def neq(self, field: str, value: Any) -> MockQueryBuilder:
        self.filters.append((field, "neq", str(value)))
        return self

    def in_(self, field: str, values: list[Any]) -> MockQueryBuilder:
        self.filters.append((field, "in", [str(v) for v in values]))
        return self

    def maybe_single(self) -> MockQueryBuilder:
        self._maybe_single_flag = True
        return self

    def single(self) -> MockQueryBuilder:
        self._single_flag = True
        return self

    def order(self, field: str, desc: bool = False) -> MockQueryBuilder:
        self.order_by = field
        self.order_desc = desc
        return self

    def limit(self, limit: int) -> MockQueryBuilder:
        self.limit_val = limit
        return self

    def range(self, start: int, end: int) -> MockQueryBuilder:
        self.offset_val = start
        self.limit_val = end - start + 1
        return self

    def or_(self, *args, **kwargs) -> MockQueryBuilder:
        return self

    def ilike(self, field: str, value: str) -> MockQueryBuilder:
        self.filters.append((field, "ilike", value))
        return self

    def is_(self, field: str, value: Any) -> MockQueryBuilder:
        self.filters.append((field, "is", value))
        return self

    def upsert(self, data: Any) -> MockQueryBuilder:
        with _db_lock:
            db = _load_db()
            rows = data if isinstance(data, list) else [data]
            items = db.setdefault(self.table_name, [])
            inserted = []
            for row in rows:
                row = dict(row)
                existing_idx = -1
                if "id" in row:
                    for idx, item in enumerate(items):
                        if item.get("id") == row["id"]:
                            existing_idx = idx
                            break
                elif "project_id" in row and self.table_name == "configurations":
                    for idx, item in enumerate(items):
                        if item.get("project_id") == row["project_id"]:
                            existing_idx = idx
                            break
                elif "page_id" in row and self.table_name in ("page_floor_links", "page_registrations"):
                    for idx, item in enumerate(items):
                        if item.get("page_id") == row["page_id"]:
                            existing_idx = idx
                            break

                if existing_idx != -1:
                    items[existing_idx].update(row)
                    items[existing_idx]["updated_at"] = datetime.now(timezone.utc).isoformat()
                    inserted.append(items[existing_idx])
                else:
                    if "id" not in row:
                        row["id"] = str(uuid.uuid4())
                    row["created_at"] = datetime.now(timezone.utc).isoformat()
                    row["updated_at"] = datetime.now(timezone.utc).isoformat()
                    items.append(row)
                    inserted.append(row)
            _save_db(db)
        self._result = inserted
        return self

    def _matches(self, item: dict) -> bool:
        for field, op, val in self.filters:
            item_val = str(item.get(field)) if item.get(field) is not None else "null"
            if op == "eq" and item_val != val:
                return False
            if op == "neq" and item_val == val:
                return False
            if op == "in" and item_val not in val:
                return False
            if op == "ilike":
                clean_val = val.replace("%", "").lower()
                if clean_val not in item_val.lower():
                    return False
            if op == "is":
                if val == "null" and item.get(field) is not None:
                    return False
                if val != "null" and item.get(field) is None:
                    return False
        return True

    def execute(self) -> MockResponse:
        if hasattr(self, "_pending_update"):
            with _db_lock:
                db = _load_db()
                items = db.setdefault(self.table_name, [])
                updated = []
                for item in _candidates(self.table_name, items, self.filters):
                    if self._matches(item):
                        for k, v in self._pending_update.items():
                            item[k] = v
                        item["updated_at"] = datetime.now(timezone.utc).isoformat()
                        updated.append(item)
                _save_db(db)
            return MockResponse(updated)

        if hasattr(self, "_pending_delete"):
            with _db_lock:
                db = _load_db()
                items = db.setdefault(self.table_name, [])
                to_delete_ids = {id(item) for item in _candidates(self.table_name, items, self.filters) if self._matches(item)}
                kept = [item for item in items if id(item) not in to_delete_ids]
                deleted = [item for item in items if id(item) in to_delete_ids]
                db[self.table_name] = kept
                _save_db(db)
            return MockResponse(deleted)

        if hasattr(self, "_result"):
            return MockResponse(self._result)

        with _db_lock:
            db = _load_db()
            items = db.setdefault(self.table_name, [])
            filtered = [item for item in _candidates(self.table_name, items, self.filters) if self._matches(item)]

        if self.order_by:
            filtered.sort(key=lambda x: str(x.get(self.order_by) or ""), reverse=self.order_desc)

        if self.limit_val is not None:
            filtered = filtered[self.offset_val : self.offset_val + self.limit_val]

        if self._single_flag or self._maybe_single_flag:
            res_data = filtered[0] if filtered else (None if self._maybe_single_flag else {})
            return MockResponse(res_data)

        return MockResponse(filtered)


class MockResponse:
    def __init__(self, data: Any):
        self.data = data


class MockClient:
    def table(self, table_name: str) -> MockQueryBuilder:
        return MockQueryBuilder(table_name)


def bulk_update_by_id(table_name: str, updates_by_id: dict[str, dict]) -> int:
    """Apply many per-row field updates to one table in a single file write.

    Callers that update N rows via N separate .update({...}).eq("id", ...)
    .execute() calls (e.g. write_global_geometry looping over every member
    of a page) trigger N full read-modify-write cycles of local_db.json in
    the mock DB -- each one dumping the ENTIRE multi-MB file back to disk.
    Besides being slow, this made the file spend most of its time mid-write,
    so any interruption (dev-server hot-reload, a second overlapping
    request) had a real chance of landing mid-json.dump and truncating/
    corrupting the whole database -- which is exactly what happened once in
    practice. Real Supabase has no such risk (proper DB, real transactions),
    so this only takes the fast path for the offline mock client; against
    real Supabase it degrades to the same per-row loop calling code used to
    do, which is fine there.
    """
    if not updates_by_id:
        return 0
    db_client = get_db()
    if not isinstance(db_client, MockClient):
        count = 0
        for row_id, fields in updates_by_id.items():
            db_client.table(table_name).update(fields).eq("id", row_id).execute()
            count += 1
        return count

    with _db_lock:
        db = _load_db()
        items = db.setdefault(table_name, [])
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for item in items:
            fields = updates_by_id.get(item.get("id"))
            if fields is None:
                continue
            for k, v in fields.items():
                item[k] = v
            item["updated_at"] = now
            count += 1
        _save_db(db)
    return count


def bulk_delete_by_id(table_name: str, ids: list[str]) -> int:
    """Delete many rows from one table in a single file write.

    Mirrors bulk_update_by_id: calling .delete().eq("id", x).execute() N
    times writes the full local_db.json N times.  On a 32-page project with
    ~10 grids/page, the old extract_grids_for_page pattern was flushing the
    65 MB file ~320 times (~4 minutes) while the job sat at 90% — causing
    the frontend stall-timeout to fire.  This replaces all those writes with
    a single atomic flush.
    """
    if not ids:
        return 0
    id_set = set(ids)
    db_client = get_db()
    if not isinstance(db_client, MockClient):
        for row_id in ids:
            db_client.table(table_name).delete().eq("id", row_id).execute()
        return len(ids)

    with _db_lock:
        db = _load_db()
        items = db.get(table_name, [])
        before = len(items)
        db[table_name] = [r for r in items if r.get("id") not in id_set]
        _save_db(db)
    return before - len(db[table_name])


def get_db() -> Any:
    """Return the Supabase Client or a fully offline MockClient fallback."""
    global _client
    if _client is None:
        cfg = get_settings()
        if (
            not cfg.supabase_url
            or "cfsrdgoapoziffjesllw" in cfg.supabase_url
            or "your_supabase_project_url" in cfg.supabase_url
        ):
            logger.warning("SUPABASE URL IS PAUSED OR DEFAULT — RUNNING IN LOCAL OFFLINE MODE (local_db.json)")
            _client = MockClient()
        else:
            try:
                _client = create_client(cfg.supabase_url, cfg.supabase_service_role_key)
                logger.info("Supabase client initialized successfully (url=%s)", cfg.supabase_url)
            except Exception as exc:
                logger.error("Failed to connect to Supabase: %s. Falling back to local offline mode.", exc)
                _client = MockClient()
    return _client
