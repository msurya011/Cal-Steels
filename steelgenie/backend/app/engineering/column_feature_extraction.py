"""
Column Feature Extraction Engine -- Phase 2 of the Column Classification
Engine mission (2026-07-15).

Classifies EACH clustered symbol candidate detect_column_symbols() already
produces into a structured (outer_boundary, inner_geometry, fill_type)
feature triple, then looks that combination up in the Universal Symbol
Library (column_symbol_library.py) for a base confidence and expected
member type. This is what lets the pipeline recognize the many real-world
column symbol styles the user pointed out directly from live drawings --
hollow square, filled square, square+dot, square+diamond, square+cross,
square+I/H, square+inner-square, circle-in-footing, diamond-in-footing --
instead of the previous four hardcoded shape-acceptance rules, which only
covered "I/H pattern", "filled rectangle", "circled I/H", and "unfilled
outline".

Deliberately additive, not a replacement: this runs ALONGSIDE the existing,
already-tuned shape-acceptance rules in detect_column_symbols (which decide
whether a sub-path becomes a raw candidate AT ALL) and the Symbol
Classification / Column Validation engines downstream (which decide
accept/reject and category). It only enriches each already-clustered
candidate with richer geometric features for those downstream stages to
use as additional evidence -- it does not itself accept or reject anything.
"""
from __future__ import annotations

import math

from app.engineering.column_symbol_library import lookup_symbol


def _shape_of_subpath(rect, items) -> tuple[str, bool]:
    """Classify ONE drawing sub-path's own geometry in isolation (no
    knowledge yet of sibling sub-paths in its cluster). Returns
    (shape_kind, has_curve). shape_kind is one of: circle, square,
    rectangle, diamond, cross, dot, line, unknown."""
    has_curve = False
    n_lines = 0
    seg_angles: list[float] = []
    h_count = v_count = 0

    for item in items:
        kind = item[0]
        if kind == "c":
            has_curve = True
        elif kind == "l":
            try:
                p1, p2 = item[1], item[2]
                dx, dy = abs(p2.x - p1.x), abs(p2.y - p1.y)
                if math.hypot(dx, dy) < 2:
                    continue
                n_lines += 1
                seg_angles.append(math.degrees(math.atan2(p2.y - p1.y, p2.x - p1.x)) % 180.0)
                if dx > dy * 1.5:
                    h_count += 1
                elif dy > dx * 1.5:
                    v_count += 1
            except Exception:
                continue
        elif kind == "re":
            try:
                rr = item[1]
                rw, rh = abs(rr.x1 - rr.x0), abs(rr.y1 - rr.y0)
                if rw >= 2 and rh >= 2:
                    n_lines += 4
                    seg_angles += [0.0, 0.0, 90.0, 90.0]
            except Exception:
                pass

    if has_curve:
        return "circle", True

    w = rect.width if rect is not None else 0
    h = rect.height if rect is not None else 0

    if w < 3 and h < 3:
        return "dot", False

    if n_lines >= 4 and seg_angles:
        # Axis-aligned (~0/90 deg) segments -> square/rectangle. Diagonal
        # (~45/135 deg) segments -> the SAME 4-line quad drawn rotated 45
        # degrees, i.e. a diamond -- the common way a diamond column/
        # pedestal mark shows up in PDF vector data (a rotated square, not
        # a distinct primitive).
        axis_hits = sum(1 for a in seg_angles if min(a, 180 - a) < 20 or abs(a - 90) < 20)
        diag_hits = sum(1 for a in seg_angles if abs(a - 45) < 20 or abs(a - 135) < 20)
        if diag_hits > axis_hits:
            return "diamond", False
        aspect = (w / h) if h > 0 else 0
        return ("square" if 0.8 <= aspect <= 1.25 else "rectangle"), False

    if n_lines == 2 and h_count >= 1 and v_count >= 1:
        return "cross", False

    if n_lines <= 1:
        return "line", False

    return "unknown", has_curve


def extract_cluster_features(drawings: list, cluster_idx: list[int]) -> dict:
    """
    Given the page's full `drawings` list (page.get_drawings()) and the
    indices belonging to ONE already-clustered symbol candidate, classify
    the cluster's outer_boundary / inner_geometry / fill_type and look the
    combination up in the Symbol Library.

    The largest sub-path by bbox area is treated as the outer boundary;
    every other sub-path whose center falls inside the outer's bbox is a
    candidate for the inner geometry -- this mirrors how a person actually
    reads these symbols (the big shape is the footing/outline, the smaller
    shape(s) inside it are the column mark).

    Returns a dict with outer_boundary, inner_geometry, fill_type, and the
    Symbol Library match (id/name/expected_member_type/confidence, all
    None if no library entry matched).
    """
    shapes = []  # (area, rect, shape_kind, is_filled)
    for k in cluster_idx:
        if k < 0 or k >= len(drawings):
            continue
        d = drawings[k]
        rect = d.get("rect")
        if rect is None:
            continue
        shape_kind, _has_curve = _shape_of_subpath(rect, d.get("items", []))
        fill = d.get("fill")
        brightness = 1.0
        if fill is not None and len(fill) >= 3:
            brightness = (fill[0] + fill[1] + fill[2]) / 3
        is_filled = brightness < 0.25
        area = max(rect.width, 0.0) * max(rect.height, 0.0)
        shapes.append((area, rect, shape_kind, is_filled))

    if not shapes:
        return {"outer_boundary": "none", "inner_geometry": "none", "fill_type": "none",
                "library_match": None, "library_name": None,
                "expected_member_type": None, "library_confidence": 0.0}

    shapes.sort(key=lambda t: -t[0])
    _outer_area, outer_rect, outer_kind, outer_filled = shapes[0]

    inner_candidates = []
    for area, rect, kind, filled in shapes[1:]:
        cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        margin = 2.0
        if (outer_rect.x0 - margin <= cx <= outer_rect.x1 + margin
                and outer_rect.y0 - margin <= cy <= outer_rect.y1 + margin):
            inner_candidates.append((area, kind, filled))

    if not inner_candidates:
        inner_geometry = "none"
    else:
        # A real I/H tick mark is usually 3+ separate short line sub-paths
        # (flanges + web) rather than one clean primitive -- recognize that
        # pattern as "i_shape" before falling back to a single dominant
        # inner shape kind.
        n_line_inner = sum(1 for _a, k, _f in inner_candidates if k in ("line", "cross"))
        if n_line_inner >= 3:
            inner_geometry = "i_shape"
        else:
            _priority = {"cross": 0, "diamond": 1, "dot": 2, "square": 3,
                         "circle": 4, "rectangle": 5, "line": 6, "unknown": 7}
            inner_candidates.sort(key=lambda t: _priority.get(t[1], 9))
            inner_kind = inner_candidates[0][1]
            if inner_kind == "dot":
                inner_geometry = "dot"
            elif inner_kind in ("square", "rectangle") and outer_kind in ("square", "rectangle"):
                inner_geometry = "inner_square"
            elif inner_kind in ("diamond", "circle", "cross"):
                inner_geometry = inner_kind
            else:
                inner_geometry = "none"

    fill_type = "filled" if outer_filled else "hollow"

    match = lookup_symbol(outer_kind, inner_geometry, fill_type)
    return {
        "outer_boundary": outer_kind,
        "inner_geometry": inner_geometry,
        "fill_type": fill_type,
        "library_match": match.id if match else None,
        "library_name": match.name if match else None,
        "expected_member_type": match.expected_member_type if match else None,
        "library_confidence": match.confidence if match else 0.0,
    }
