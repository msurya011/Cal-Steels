"""
Beam Leader & Arrow Association Engine (AISC & Blueprint Standard).

Resolves structural beam profiles for:
1. Outside Leader Arrows (callouts placed outside the framing bay pointing in).
2. Dogleg / Forked Leaders (callout pointing to multiple adjacent beams).
3. Spanning Row Arrows (e.g. ◄── W16x31 ──► spanning across repeated infill beams).
4. Direct Point-to-Line Arrows.

Preserves explicit individual beam labels (Rule 1) and falls back to Unlabeled
for beams without arrows (Rule 3).
"""

from __future__ import annotations
import math
import re
from typing import Dict, List, Tuple, Optional, Any
import fitz


def _distance_point_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Perpendicular distance from point (px, py) to line segment (x1, y1)-(x2, y2)."""
    dx = x2 - x1
    dy = y2 - y1
    L2 = dx * dx + dy * dy
    if L2 <= 1e-6:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _segments_intersect(
    ax1: float, ay1: float, ax2: float, ay2: float,
    bx1: float, by1: float, bx2: float, by2: float
) -> bool:
    """Check if 2D line segment A intersects line segment B."""
    def ccw(x1, y1, x2, y2, x3, y3):
        return (y3 - y1) * (x2 - x1) > (y2 - y1) * (x3 - x1)

    return (
        ccw(ax1, ay1, bx1, by1, bx2, by2) != ccw(ax2, ay2, bx1, by1, bx2, by2) and
        ccw(ax1, ay1, ax2, ay2, bx1, by1) != ccw(ax1, ay1, ax2, ay2, bx2, by2)
    )


def extract_leader_arrows(page: "fitz.Page", rot_mat=None) -> List[Dict[str, Any]]:
    """
    Extract all vector leader lines, arrows, and spanning callout paths from CAD vector data.
    """
    drawings = page.get_drawings()
    leaders = []

    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        items = d.get("items", [])
        if not items:
            continue

        for item in items:
            if item[0] == "l":  # Line segment
                p1, p2 = item[1], item[2]
                if rot_mat is not None:
                    p1 = p1 * rot_mat
                    p2 = p2 * rot_mat

                length = math.hypot(p2.x - p1.x, p2.y - p1.y)
                if 10.0 <= length <= 600.0:
                    leaders.append({
                        "x1": p1.x, "y1": p1.y,
                        "x2": p2.x, "y2": p2.y,
                        "length": length,
                        "is_horizontal": abs(p2.y - p1.y) <= abs(p2.x - p1.x),
                        "width": d.get("width", 1.0),
                    })

def _trace_leader_chains(
    leader_lines: List[Dict[str, Any]],
    start_pt: Tuple[float, float],
    max_hops: int = 4,
    connect_tol: float = 8.0,
    start_search_r: float = 35.0,
) -> List[List[Dict[str, Any]]]:
    """
    Trace connected leader line segments from a margin callout text point into the framing.
    Handles multi-segment dogleg leaders: horizontal shoulder -> angled shank -> pointer tip.
    """
    chains: List[List[Dict[str, Any]]] = []

    def dfs(cur_pt: Tuple[float, float], path: List[Dict[str, Any]], used_indices: set):
        extended = False
        for idx, ldr in enumerate(leader_lines):
            if idx in used_indices:
                continue
            p1 = (ldr["x1"], ldr["y1"])
            p2 = (ldr["x2"], ldr["y2"])
            d1 = math.hypot(cur_pt[0] - p1[0], cur_pt[1] - p1[1])
            d2 = math.hypot(cur_pt[0] - p2[0], cur_pt[1] - p2[1])

            if d1 <= connect_tol and len(path) < max_hops:
                dfs(p2, path + [ldr], used_indices | {idx})
                extended = True
            elif d2 <= connect_tol and len(path) < max_hops:
                dfs(p1, path + [ldr], used_indices | {idx})
                extended = True

        if not extended and path:
            chains.append(path)

    # Find initial leader segment starting near start_pt
    for idx, ldr in enumerate(leader_lines):
        p1 = (ldr["x1"], ldr["y1"])
        p2 = (ldr["x2"], ldr["y2"])
        d1 = math.hypot(start_pt[0] - p1[0], start_pt[1] - p1[1])
        d2 = math.hypot(start_pt[0] - p2[0], start_pt[1] - p2[1])
        d_seg = _distance_point_to_segment(start_pt[0], start_pt[1], ldr["x1"], ldr["y1"], ldr["x2"], ldr["y2"])

        if min(d1, d2, d_seg) <= start_search_r:
            if d1 <= d2:
                dfs(p2, [ldr], {idx})
            else:
                dfs(p1, [ldr], {idx})

    return chains


def resolve_arrow_linked_beams(
    page: "fitz.Page",
    profiles: List[Dict[str, Any]],
    beam_line_map: Dict[int, Dict[str, Any]],
    all_struct_lines: List[Tuple[float, float, float, float, float]],
    pts_per_foot: float = 9.0,
) -> Dict[int, Dict[str, Any]]:
    """
    Trace leader arrows and spanning callout lines (including margin callouts and doglegs)
    to propagate beam section profiles.
    
    Returns a dictionary of:
      { struct_line_idx: { "profile": "W16x31", "source": "arrow_propagated", "profile_idx": idx } }
    """
    if not profiles or not all_struct_lines:
        return {}

    rot_mat = page.rotation_matrix if page.rotation != 0 else None
    leader_lines = extract_leader_arrows(page, rot_mat=rot_mat)
    if not leader_lines:
        return {}

    claimed_line_keys = set()
    for prof_idx, hit in beam_line_map.items():
        hx1, hy1, hx2, hy2 = hit["x1"], hit["y1"], hit["x2"], hit["y2"]
        claimed_line_keys.add((round(hx1, 1), round(hy1, 1), round(hx2, 1), round(hy2, 1)))
        claimed_line_keys.add((round(hx2, 1), round(hy2, 1), round(hx1, 1), round(hy1, 1)))

    propagated_map: Dict[int, Dict[str, Any]] = {}
    LEADER_CONNECT_R = max(28.0, pts_per_foot * 2.8) if pts_per_foot > 0 else 35.0

    for prof_idx, prof in enumerate(profiles):
        cx = prof.get("cx", 0)
        cy = prof.get("cy", 0)
        prof_name = prof.get("profile", "")
        if not prof_name:
            continue

        # Trace direct and multi-segment leader chains starting from this profile text (in margins or inside)
        chains = _trace_leader_chains(
            leader_lines,
            (cx, cy),
            max_hops=4,
            connect_tol=10.0,
            start_search_r=LEADER_CONNECT_R,
        )

        # Collect all segments reached by these chains
        candidate_segments = []
        if chains:
            for chain in chains:
                candidate_segments.extend(chain)
        else:
            # Fallback: direct single segments near text
            for ldr in leader_lines:
                d_start = math.hypot(ldr["x1"] - cx, ldr["y1"] - cy)
                d_end = math.hypot(ldr["x2"] - cx, ldr["y2"] - cy)
                d_seg = _distance_point_to_segment(cx, cy, ldr["x1"], ldr["y1"], ldr["x2"], ldr["y2"])
                if min(d_start, d_end, d_seg) <= LEADER_CONNECT_R:
                    candidate_segments.append(ldr)

        if not candidate_segments:
            continue

        # For each segment reached by the leader arrow path, test which unclaimed structural beam lines it reaches
        for ldr in candidate_segments:
            lx1, ly1, lx2, ly2 = ldr["x1"], ldr["y1"], ldr["x2"], ldr["y2"]

            for line_idx, (bx1, by1, bx2, by2, blen) in enumerate(all_struct_lines):
                key = (round(bx1, 1), round(by1, 1), round(bx2, 1), round(by2, 1))
                if key in claimed_line_keys or line_idx in propagated_map:
                    continue

                intersects = _segments_intersect(lx1, ly1, lx2, ly2, bx1, by1, bx2, by2)
                touches_start = _distance_point_to_segment(lx1, ly1, bx1, by1, bx2, by2) <= 10.0
                touches_end = _distance_point_to_segment(lx2, ly2, bx1, by1, bx2, by2) <= 10.0

                if intersects or touches_start or touches_end:
                    propagated_map[line_idx] = {
                        "profile": prof_name,
                        "source": "margin_leader_arrow" if "margin" in prof.get("location", "") else "arrow_propagated",
                        "profile_idx": prof_idx,
                        "x1": bx1, "y1": by1, "x2": bx2, "y2": by2,
                        "length_pt": blen,
                    }

    return propagated_map


def _extract_page_typical_notes(page: "fitz.Page") -> List[Dict[str, Any]]:
    """
    Extract typical structural notes from blueprint text (e.g. 'W10x15, TYP U.N.O.', 'ALL BEAMS W16x31 U.N.O.').
    """
    notes = []
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []):
            line_str = " ".join(span.get("text", "") for span in line.get("spans", "")).strip()
            if not line_str:
                continue
            
            # Check for typical profile note pattern: e.g. W10x15, TYP U.N.O.
            m = re.search(r"\b([WwCcSsHhSsPpLl]\d+[\w\.\/xX\-]+)[,\s]+(?:TYP|TYPICAL)\b", line_str, re.IGNORECASE)
            if m:
                prof = m.group(1).upper().replace("X", "x")
                bbox = line.get("bbox", [0, 0, 0, 0])
                notes.append({
                    "profile": prof,
                    "text": line_str,
                    "cx": (bbox[0] + bbox[2]) / 2.0,
                    "cy": (bbox[1] + bbox[3]) / 2.0,
                    "is_opening_note": bool(re.search(r"split|opening|supt|header", line_str, re.IGNORECASE)),
                })
    return notes


def propagate_bay_typical_beams(
    page: "fitz.Page",
    profiles: List[Dict[str, Any]],
    beam_line_map: Dict[int, Dict[str, Any]],
    unlabeled_profiles: List[Dict[str, Any]],
    unlabeled_line_map: Dict[int, Dict[str, Any]],
    v_grid: Optional[List[float]] = None,
    h_grid: Optional[List[float]] = None,
    pts_per_foot: float = 9.0,
) -> int:
    """
    Automatically fills unlabeled / empty infill beams in framing bays where
    sibling parallel beams share a dominant typical section profile (or a typical note).
    
    Returns the number of beams auto-filled.
    """
    if not unlabeled_profiles or not profiles:
        return 0

    typical_notes = _extract_page_typical_notes(page)
    opening_note_prof = next((n["profile"] for n in typical_notes if n.get("is_opening_note")), None)
    general_note_prof = next((n["profile"] for n in typical_notes if not n.get("is_opening_note")), None)

    # Sort grids if available
    v_sorted = sorted(v_grid) if v_grid and len(v_grid) >= 2 else None
    h_sorted = sorted(h_grid) if h_grid and len(h_grid) >= 2 else None

    # Helper to find bounding bay for a point
    def get_bay_bounds(x: float, y: float) -> Tuple[float, float, float, float]:
        if v_sorted and h_sorted:
            # Find v_grid interval
            gx1, gx2 = v_sorted[0] - 50.0, v_sorted[-1] + 50.0
            for i in range(len(v_sorted) - 1):
                if v_sorted[i] - 15.0 <= x <= v_sorted[i+1] + 15.0:
                    gx1, gx2 = v_sorted[i], v_sorted[i+1]
                    break

            # Find h_grid interval
            gy1, gy2 = h_sorted[0] - 50.0, h_sorted[-1] + 50.0
            for j in range(len(h_sorted) - 1):
                if h_sorted[j] - 15.0 <= y <= h_sorted[j+1] + 15.0:
                    gy1, gy2 = h_sorted[j], h_sorted[j+1]
                    break
            return gx1, gx2, gy1, gy2
        return (0.0, 99999.0, 0.0, 99999.0)

    auto_filled_count = 0

    for syn_idx, (u_prof, u_hit) in enumerate(zip(unlabeled_profiles, unlabeled_line_map.values())):
        ux, uy = u_prof["cx"], u_prof["cy"]
        u_dir = u_hit.get("dir", u_prof.get("dir_hint", "V"))
        u_len = u_hit.get("length_pt", 0.0)

        gx1, gx2, gy1, gy2 = get_bay_bounds(ux, uy)

        # Collect labeled sibling beams in the same framing bay or corridor
        sibling_profiles = []
        for p_idx, p in enumerate(profiles):
            if p.get("unlabeled") or p.get("profile") in ("?", "", None):
                continue
            hit = beam_line_map.get(p_idx)
            if not hit:
                continue
            
            p_dir = hit.get("dir", p.get("dir_hint", "V"))
            if p_dir != u_dir:
                continue

            px, py = p["cx"], p["cy"]
            p_len = hit.get("length_pt", 0.0)
            
            # Check for bay membership or parallel corridor proximity
            is_sibling = False
            if u_dir == "V":
                # Parallel vertical beams within similar X corridor (same or adjacent bay) and overlapping Y
                if abs(px - ux) <= max(220.0, (gx2 - gx1) * 1.5) and abs(py - uy) <= max(180.0, u_len * 0.75):
                    is_sibling = True
            elif u_dir == "H":
                # Parallel horizontal beams within similar Y corridor and overlapping X
                if abs(py - uy) <= max(220.0, (gy2 - gy1) * 1.5) and abs(px - ux) <= max(180.0, u_len * 0.75):
                    is_sibling = True
            else:
                # Diagonal
                if math.hypot(px - ux, py - uy) <= 250.0:
                    is_sibling = True

            if is_sibling:
                sibling_profiles.append({
                    "profile": p["profile"],
                    "length_pt": p_len,
                    "dist": math.hypot(px - ux, py - uy),
                })

        # Calculate dominant profile for this bay & direction
        assigned_profile = None
        assigned_source = "bay_typical_propagated"

        if sibling_profiles:
            from collections import Counter
            # Prefer profiles with similar span length (+- 35%)
            span_matched = [s for s in sibling_profiles if abs(s["length_pt"] - u_len) <= max(40.0, u_len * 0.35)]
            cand_pool = span_matched if span_matched else sibling_profiles
            prof_counts = Counter(s["profile"] for s in cand_pool)
            dominant_prof, count = prof_counts.most_common(1)[0]
            
            # Find median span of dominant sibling beams
            dom_spans = [s["length_pt"] for s in sibling_profiles if s["profile"] == dominant_prof]
            dom_span = sorted(dom_spans)[len(dom_spans) // 2] if dom_spans else u_len

            # If this unlabeled beam is a significantly shorter opening/split header and opening note exists
            if opening_note_prof and u_len < dom_span * 0.60:
                assigned_profile = opening_note_prof
                assigned_source = "opening_note_propagated"
            else:
                assigned_profile = dominant_prof
                assigned_source = "bay_typical_propagated"
        elif general_note_prof:
            assigned_profile = general_note_prof
            assigned_source = "general_note_propagated"

        if assigned_profile:
            u_prof["profile"] = assigned_profile
            u_prof["source"] = assigned_source
            u_prof["unlabeled"] = False
            u_prof["is_auto_filled"] = True
            auto_filled_count += 1

    return auto_filled_count
