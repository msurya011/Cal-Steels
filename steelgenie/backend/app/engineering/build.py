"""
Build orchestrator — the entry point the API/worker call.

Pulls validated members + project configuration, then produces:
  - bom_items: main member rows (weights from the shapes library) plus
    accessory rows (plates/angles/bolts/weld studs) from the connection
    design engine, piecemarked
  - column_groups: vertical column stacks with splice/base-plate/anchor data
  - braced_frames: brace groupings per elevation sheet

Determinism: identical members + identical configuration always produce the
same output (no randomness, no external calls) — see ENGINE_VERSION.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Tuple

from app.engineering import ENGINE_VERSION, shapes
from app.engineering.braces import group_braces
from app.engineering.columns import group_columns
from app.engineering.connections import design_simple_connection
from app.engineering.reactions import compute_beam_reaction_kips

logger = logging.getLogger(__name__)

_CATEGORY_BY_KIND = {
    "beam": "Beams",
    "column": "Columns",
    "vbrace": "Vertical Braces",
    "hbrace": "Horizontal Braces",
    "joist": "Joists",
}
_MARK_PREFIX_BY_KIND = {"beam": "B", "column": "C", "vbrace": "VB", "hbrace": "HB", "joist": "J"}


def _main_bom_row(project_id: str, member: Dict[str, Any], piecemark: str, page: Dict[str, Any]) -> Dict[str, Any]:
    kind = member.get("kind", "beam")
    section = member.get("section")
    length_ft = member.get("length_ft") or 0
    geo = member.get("geometry") or {}
    resolution_status = geo.get("resolution_status")
    source_page_num = geo.get("source_page_num")

    comment = None
    if resolution_status == "resolved" and source_page_num:
        comment = f"Resolved from Page {source_page_num}"
    elif resolution_status == "unresolved":
        comment = "Unresolved reference"
        if not section or section == "Column":
            section = "Unresolved"

    wt_per_ft = shapes.get_weight_per_ft(section)
    weight_lbs = round(wt_per_ft * length_ft, 2) if wt_per_ft and length_ft else None

    return {
        "project_id": project_id,
        "piecemark": piecemark,
        "category": _CATEGORY_BY_KIND.get(kind, "Other"),
        "qty": 1,
        "section_type": shapes.section_type_of(section),
        "section": section,
        "length_in": round(length_ft * 12, 2) if length_ft else None,
        "grade": member.get("grade") or "A992",
        "weight_lbs": weight_lbs,
        "camber": 0.0,
        "cope": 0,
        "holes": 0,
        "weld_studs": 0,
        "is_main": True,
        "status": "not_started",
        "member_id": member.get("id"),
        "drawing_id": page.get("drawing_id"),
        "sheet": f"{page.get('drawing_filename') or 'Drawing'} — Page {page.get('idx', 0) + 1}",
        "comment": comment,
        "dcr_left": None,
        "dcr_right": None,
    }


def _accessory_bom_rows(project_id: str, main_piecemark: str, accessories: List[Dict[str, Any]], page: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for acc in accessories:
        rows.append({
            "project_id": project_id,
            "piecemark": main_piecemark,
            "category": acc["category"],
            "qty": acc["qty"],
            "section_type": acc.get("section_type"),
            "section": acc.get("section"),
            "length_in": None,
            "grade": acc.get("grade"),
            "weight_lbs": acc.get("weight_lbs") or 0.0,
            "camber": 0.0,
            "cope": 0,
            "holes": 0,
            # Only the Weld Studs accessory row actually represents stud
            # count — everything else (angles/plates/bolts) stays 0 here.
            "weld_studs": acc["qty"] if acc["category"] == "Weld Studs" else 0,
            "is_main": False,
            "status": "not_started",
            "drawing_id": page.get("drawing_id"),
            "sheet": f"{page.get('drawing_filename') or 'Drawing'} — Page {page.get('idx', 0) + 1}",
            "comment": None,
            "dcr_left": None,
            "dcr_right": None,
        })
    return rows


def run_build(
    project_id: str,
    config: Dict[str, Any],
    members_by_page: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]],
) -> Dict[str, Any]:
    """
    `members_by_page` must already be sorted floor-to-floor (ascending
    tos_ft, falling back to page idx) — the caller (workers/build.py) owns
    fetching + ordering so this module stays a pure function of its inputs.
    """
    bom_rows: List[Dict[str, Any]] = []
    warnings: List[str] = []
    piecemark_counters: Dict[str, int] = {}
    # Every member that doesn't make it into the BOM gets counted here, by
    # kind, so the caller can surface an honest "N members were left out of
    # the BOM because X" summary instead of silently under-reporting weight.
    skipped_by_kind: Dict[str, int] = {}
    skipped_suggested: int = 0

    for page, members in members_by_page:
        for m in members:
            if m.get("status") == "excluded":
                continue
            kind = m.get("kind", "beam")
            section = m.get("section")
            sec_str = (section or "").strip().upper()
            geo = m.get("geometry") or {}

            # Unified deterministic member classifier:
            is_explicit_beam = (kind == "beam") and bool(re.match(r"^(?:W\d|HSS|C\d|MC\d|L\d|PIPE|ISA)", sec_str))
            is_explicit_joist = (kind == "joist") or bool(re.search(r"\d{1,2}(?:K|LH|DLH|KSP|G|CJ|CS)", sec_str)) or ("JOIST" in sec_str)

            if kind == "column":
                resolved_sec = geo.get("resolved_profile") or geo.get("profile")
                if resolved_sec:
                    section = resolved_sec
                    m["section"] = resolved_sec
                elif not section:
                    section = m.get("piecemark") or "Column"
                    m["section"] = section
                if not m.get("length_ft"):
                    m["length_ft"] = 14.0
            elif is_explicit_joist or (not is_explicit_beam and kind != "footing"):
                kind = "joist"
                m["kind"] = "joist"
            elif is_explicit_beam or kind == "beam":
                kind = "beam"
                m["kind"] = "beam"

            if not section:
                if geo.get("suggested") or m.get("source") == "suggested":
                    skipped_suggested += 1
                    continue
                else:
                    skipped_by_kind[kind] = skipped_by_kind.get(kind, 0) + 1
                    continue

            prefix = _MARK_PREFIX_BY_KIND.get(kind, "X")
            piecemark_counters[prefix] = piecemark_counters.get(prefix, 0) + 1
            piecemark = f"{prefix}{piecemark_counters[prefix]}"

            bom_rows.append(_main_bom_row(project_id, m, piecemark, page))

            if kind in ("beam", "joist"):
                reaction = compute_beam_reaction_kips(m, config)
                connection = design_simple_connection(m, reaction, config)
                bom_rows.extend(_accessory_bom_rows(project_id, piecemark, connection["accessories"], page))

    for kind, count in skipped_by_kind.items():
        label = _CATEGORY_BY_KIND.get(kind, kind)
        warnings.append(f"{count} {label} member(s) skipped from BOM — no section assigned.")
    if skipped_suggested:
        warnings.append(
            f"{skipped_suggested} unconfirmed/suggested member(s) skipped from BOM — "
            f"review and confirm them on the takeoff before they'll be included."
        )

    column_groups = group_columns(members_by_page, config)
    braced_frames = group_braces(members_by_page, config)

    for g in column_groups:
        warnings.extend(g.pop("warnings", []) or [])

    return {
        "engine_version": ENGINE_VERSION,
        "bom_items": bom_rows,
        "column_groups": column_groups,
        "braced_frames": braced_frames,
        "warnings": sorted(set(warnings)),
        "stats": {
            "bom_item_count": len(bom_rows),
            "column_group_count": len(column_groups),
            "braced_frame_count": len(braced_frames),
            "skipped_count": sum(skipped_by_kind.values()) + skipped_suggested,
        },
    }
