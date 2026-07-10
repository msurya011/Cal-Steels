"""
Column Scheduler engine — groups columns into vertical stacks across floors,
applies auto-splicing above a configured max section height, and assigns a
base-plate/anchor-bolt spec at the lowest floor of each stack.

Grouping heuristic: columns sharing (approximately) the same page-relative
(x, y) footprint across different pages of the same project are treated as
one vertical stack — i.e. the same physical column repeated on each floor
framing plan. Pages are ordered by Top-of-Steel elevation (falling back to
sheet index) so "floor 1" of a group is genuinely the lowest.

This is a deterministic MVP grouping — it does not yet reconcile grid-line
labels across sheets (tracked as a follow-up alongside true plan-reaction
OCR in reactions.py).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.engineering import shapes

_POSITION_TOLERANCE = 0.012  # page-fraction units; matches the ~0.01 tolerance used elsewhere in the extraction pipeline


def _cluster_key(x: float, y: float, tol: float) -> Tuple[float, float]:
    return (round(x / tol) * tol, round(y / tol) * tol)


def group_columns(
    members_by_page: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]],
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    `members_by_page`: list of (page_row, [member_row, ...]) ordered floor-to-floor
    (caller sorts by tos_ft ascending, falling back to idx).
    Returns a list of column_groups rows ready for insertion.
    """
    conn_cfg = config.get("connection_types") or {}
    auto_splice = bool(conn_cfg.get("auto_splice", False))
    max_height_ft = float(conn_cfg.get("max_splice_height_ft", 35.0))
    splice_method = conn_cfg.get("column_splice_method", "welded_flange")
    materials = config.get("materials") or {}

    # Build clusters keyed by rounded (x, y); each cluster accumulates one
    # entry per floor it appears on.
    clusters: Dict[Tuple[float, float], List[Dict[str, Any]]] = {}

    for page, members in members_by_page:
        floor_label = page.get("title") or page.get("sheet_no") or f"Level {page.get('idx', 0) + 1}"
        floor_elev = page.get("tos_ft")
        for m in members:
            if m.get("kind") != "column" or m.get("status") == "excluded":
                continue
            geom = m.get("geometry") or {}
            x, y = geom.get("x"), geom.get("y")
            if x is None or y is None:
                continue
            key = _cluster_key(float(x), float(y), _POSITION_TOLERANCE)
            clusters.setdefault(key, []).append({
                "member_id": m.get("id"),
                "page_id": page.get("id"),
                "floor_label": floor_label,
                "floor_elev_ft": floor_elev,
                "section": m.get("section"),
                "grid_ref": geom.get("grid_ref"),
            })

    groups: List[Dict[str, Any]] = []
    for i, (key, floors) in enumerate(sorted(clusters.items(), key=lambda kv: (kv[0][1], kv[0][0])), start=1):
        floors_sorted = sorted(
            floors, key=lambda f: (f["floor_elev_ft"] is None, f["floor_elev_ft"] or 0)
        )
        member_ids = [f["member_id"] for f in floors_sorted]
        grids = sorted({f["grid_ref"] for f in floors_sorted if f.get("grid_ref")})

        # Cumulative height from base; insert a splice marker whenever the
        # running height crosses max_height_ft.
        splices: List[Dict[str, Any]] = []
        warnings: List[str] = []
        if auto_splice and len(floors_sorted) > 1:
            base_elev = floors_sorted[0]["floor_elev_ft"] or 0
            for f in floors_sorted[1:]:
                elev = f.get("floor_elev_ft")
                if elev is None:
                    warnings.append("Missing Top-of-Steel elevation on one or more floors — splice heights may be inaccurate.")
                    continue
                if (elev - base_elev) > max_height_ft:
                    splices.append({
                        "below_floor": f["floor_label"],
                        "elevation_ft": elev,
                        "method": splice_method,
                    })
                    base_elev = elev

        base_section = floors_sorted[0]["section"]
        depth_in = shapes.get_depth_in(base_section) or 12.0
        base_plate = {
            "length_in": round(depth_in + 6, 1),
            "width_in": round(depth_in + 6, 1),
            "thickness_in": 1.5 if depth_in <= 12 else 2.0,
            "grade": materials.get("PLATE", "A50"),
        }
        anchors = {
            "count": 4,
            "diameter_in": 1.25,
            "grade": materials.get("ANCHOR", "Gr36"),
        }

        groups.append({
            "name": f"Column Group {i}",
            "column_ids": member_ids,
            "grids": grids,
            "floors": floors_sorted,
            "splice": {"points": splices} if splices else None,
            "base_plate": base_plate,
            "anchors": anchors,
            "warnings": warnings,
        })

    return groups
