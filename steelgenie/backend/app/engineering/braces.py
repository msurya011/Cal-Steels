"""
Braced Frame Scheduler engine — groups vertical/horizontal brace members into
named "braced frame" elevations.

Grouping heuristic: braces sharing a page are grouped into one frame per
page (a framing/elevation sheet in this schema does not yet distinguish
plan-view vs elevation-view braces, so "one frame per sheet that contains
braces" is the practical MVP proxy — refining this to true grid-bay
elevations is a follow-up once elevation sheets are classified separately
from plan sheets).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


def group_braces(
    members_by_page: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]],
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    seismic_cfg = config.get("seismic") or {}
    frame_type = seismic_cfg.get("brace_frame", "non_seismic")
    conn_cfg = config.get("connection_types") or {}
    brace_connection = conn_cfg.get("vertical_brace", "welded")

    frames: List[Dict[str, Any]] = []
    for page, members in members_by_page:
        braces = [m for m in members if m.get("kind") in ("vbrace", "hbrace") and m.get("status") != "excluded"]
        if not braces:
            continue

        sections = sorted({m.get("section") for m in braces if m.get("section")})
        frames.append({
            "name": f"Brace Elevation — {page.get('title') or page.get('sheet_no') or ('Page ' + str(page.get('idx', 0) + 1))}",
            "page_id": page.get("id"),
            "brace_ids": [m.get("id") for m in braces],
            "brace_count": len(braces),
            "sections": sections,
            "frame_type": frame_type,
            "connection_method": brace_connection,
            "geometry": {
                "braces": [
                    {
                        "member_id": m.get("id"),
                        "section": m.get("section"),
                        "geometry": m.get("geometry"),
                    }
                    for m in braces
                ]
            },
        })

    return frames
