"""
Supabase client helpers — thin wrappers around the supabase-py client.
Includes a fully compliant local offline Mock DB engine when Supabase is unresolvable.
"""
from __future__ import annotations

import logging
import os
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

from supabase import Client, create_client
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[Any] = None

# Local database file path
_DB_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "local_db.json"
)


def _load_db() -> dict:
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
        "braced_frames": []
    }
    if not os.path.exists(_DB_FILE):
        db = default_db
    else:
        try:
            with open(_DB_FILE, "r") as f:
                db = json.load(f)
        except Exception:
            db = default_db

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

    return db


def _save_db(data: dict) -> None:
    try:
        with open(_DB_FILE, "w") as f:
            json.dump(data, f, indent=2)
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
        db = _load_db()
        items = db.setdefault(self.table_name, [])
        updated = []
        for item in items:
            if self._matches(item):
                for k, v in data.items():
                    item[k] = v
                item["updated_at"] = datetime.now(timezone.utc).isoformat()
                updated.append(item)
        _save_db(db)
        self._result = updated
        return self

    def delete(self) -> MockQueryBuilder:
        db = _load_db()
        items = db.setdefault(self.table_name, [])
        kept = []
        deleted = []
        for item in items:
            if self._matches(item):
                deleted.append(item)
            else:
                kept.append(item)
        db[self.table_name] = kept
        _save_db(db)
        self._result = deleted
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
        if hasattr(self, "_result"):
            return MockResponse(self._result)

        db = _load_db()
        items = db.setdefault(self.table_name, [])
        filtered = [item for item in items if self._matches(item)]

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


def get_db() -> Any:
    """Return the Supabase Client or a fully offline MockClient fallback."""
    global _client
    if _client is None:
        cfg = get_settings()
        # Fallback to local file-based database if Supabase URL is paused/placeholder
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
