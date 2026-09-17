"""
Grid CHAIN-LINE geometry: the grid line is the measurement axis, not the bubble.

Why this module exists
----------------------
Everywhere else in this codebase a grid's position is taken from where its
BUBBLE sits -- `_find_confirmed_bubbles` stores the centre of the label's text
span, `_build_axis_tracks` copies that into `coord`, and `_make_bays` measures
bubble-centre to bubble-centre. `main.extract_grid_lines` says so outright:
"Extract the X positions of vertical grid lines ... from grid bubble label
text."

That is only correct while every bubble sits exactly on its own line, and on
real sheets it does not:

  * At tight grid spacing the drafter DODGES the bubbles sideways (or stacks
    them on a short leader) so they don't overlap. Sub-grids inserted between
    two primaries -- 2.1, 4.1, 5.1, 8.4, 9.1, B.9, D.1 -- are where this
    happens most, and they are exactly the grids whose bays are smallest, so
    the absolute error lands on the span least able to absorb it.
  * The stored coordinate is the centre of the TEXT bbox, not of the circle.
    A two-character label ("10", "B.9") is not centred the same way a
    one-character label is.
  * A bubble pulled out on a leader line can sit several feet off its grid.

The bubble is a LABEL. The chain (long-dash-short-dash) line it terminates is
the measurement axis. This module recovers that line's true coordinate from the
page's own vector paths, so a bay length is a line-to-line distance.

Vector, not raster
------------------
`page.get_drawings()` already gives the chain line as path geometry -- the same
call `_find_confirmed_bubbles` uses to confirm the bubble circle. No Canny, no
Hough, no DPI guessing, and the result is exact rather than sampled. Raster
fallback is only needed for scanned sheets, which this module deliberately does
not attempt: it reports "no line found" and lets the caller keep the old
bubble-inferred coordinate, flagged as such.

Public API
----------
    build_line_index(page, page_w, page_h, rot_mat=None) -> LineIndex
    attach_line_coords(confirmed, line_index)  -> mutates dicts in place
    grid_coord(bubble, pos_key)               -> (coord, source)

`attach_line_coords` adds to each confirmed-bubble dict:
    line_cx        float | None  -- x of the vertical chain line it terminates
    line_cy        float | None  -- y of the horizontal chain line it terminates
    line_cx_source str           -- "vector_line" | "bubble_inferred"
    line_cy_source str
    line_cx_delta  float | None  -- how far the bubble sat off its own line
    line_cy_delta  float | None

Nothing here ever raises on a malformed page: a sheet with no usable vector
geometry yields an empty index and every caller falls back to prior behaviour.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import fitz

# ---------------------------------------------------------------------------
# Tuning constants
#
# All in PDF points (1 pt = 1/72"). At the 1/8" = 1'-0" scale these sheets are
# drawn at, 9 pts = 1 foot, so the tolerances below are deliberately stated in
# feet-equivalents to keep them honest.
# ---------------------------------------------------------------------------

# A segment counts as axis-aligned if its off-axis drift is under this.
AXIS_TOL_PTS = 0.75

# Ignore hairline fragments -- hatch ticks, arrowheads, dimension witness nibs.
MIN_SEGMENT_PTS = 6.0

# Two segments belong to the same line when their coordinates agree within this.
CLUSTER_TOL_PTS = 1.2

# Grid lines are thin. Anything heavier is a wall, a beam, or a border.
MAX_STROKE_WIDTH = 2.6

# A grid line must run at least this fraction of the sheet's extent in its own
# direction. Sub-grids terminate early (spanning 1-2 bays, ~100-250pt); hence
# the threshold allows local sub-grid lines while filtering stray ticks.
MIN_EXTENT_FRAC = 0.035

# How far a bubble may sit from its line, perpendicular to the line. At 9 pts
# per foot this is a little under 3 feet -- generous enough for a dodged
# sub-grid bubble, tight enough that the NEXT grid line is never a candidate
# (the smallest real bay in the reference set is 12'-5 1/8").
BUBBLE_TO_LINE_TOL_PTS = 26.0

# How far the line's nearer END may sit from the bubble, along the line. A grid
# line terminates AT its bubble, so this should be small; the slack covers the
# gap the drafter leaves between the line end and the circle.
LINE_END_TO_BUBBLE_TOL_PTS = 90.0

# A dashed stroke is strong evidence of a chain line. Expressed as a bonus
# subtracted from the match cost, in points.
DASH_BONUS_PTS = 4.0

# Most CAD exports draw the chain line as a run of separate short segments
# rather than one stroke carrying a PDF dash pattern -- on the sample sheets
# `dashes` is empty on every grid line, while the real line arrives as 15-50
# collinear segments. Segment count is therefore the chain signal that
# actually fires, so it earns its own (smaller) bonus. Kept well below the
# coordinate term so proximity still decides.
SEGMENT_CHAIN_MIN = 6
SEGMENT_CHAIN_BONUS_PTS = 2.5

# Agreement dead band. Measured on the sample sheets: on a VECTOR CAD export
# the bubble block is placed ON its grid line, so bubble centre and line
# coordinate already agree to a fraction of a point, and swapping one exact
# value for another introduces only this module's own matching noise -- an A/B
# over 68 dimensioned bays moved the median error against the sheets' own
# printed dimension strings from 0.1" to 0.8", worsening 23 bays to improve 8.
# So inside the dead band the bubble WINS and the line is used only as
# confirmation. The line's job is to catch the case the bubble genuinely gets
# wrong: a bubble dodged clear of its line to make room, which is a
# displacement of feet, not tenths of an inch. Expressed as a fraction of the
# axis's own median bay so it travels across drawing scales, with a floor for
# very small bays.
AGREE_BAND_FRAC_OF_MEDIAN_BAY = 0.015
AGREE_BAND_FLOOR_PTS = 2.0

# Evidence required before the line is allowed to OVERRIDE the bubble.
#
# Outside the dead band there are two stories that fit the same measurement:
# the drafter dodged the bubble (line right, bubble wrong), or this module
# latched onto the wrong line (bubble right, line wrong). They are told apart
# by the quality of the line, not by the size of the gap:
#
#   * a real grid line runs most of the plan -- a short fragment sharing a
#     coordinate with a grid is a wall face, a witness line, or a joist;
#   * the match must be unambiguous -- when the runner-up candidate scores
#     nearly as well, the choice between them is a coin flip, and a coin flip
#     is not grounds for overriding a coordinate that is probably already
#     right.
#
# Tuned against the A/B: on clean vector sheets these gates fire on nothing,
# so the pass confirms and never degrades. They exist for the sheet where a
# bubble really was pushed clear of its line.
MIN_CORRECT_LEN_FRAC = 0.18
MIN_CORRECT_MARGIN_PTS = 2.0

# Safety net for a bubble that matched the wrong line. Applied after a track's
# chain exists, when the axis's own typical bay spacing is finally known: a
# line-derived coordinate that moved the grid by more than this fraction of the
# median bay is not a drafter's dodge, it is a mis-match, and the bubble
# coordinate is restored. Deliberately loose -- it exists to catch gross
# errors, not to second-guess ordinary dodges.
OUTLIER_FRAC_OF_MEDIAN_BAY = 0.25


class LineIndex:
    """Axis-aligned candidate chain lines recovered from a page's vector paths."""

    __slots__ = ("vertical", "horizontal", "page_w", "page_h", "stats", "all_thin_segments", "skewed")

    def __init__(self, vertical, horizontal, page_w, page_h, stats, all_thin_segments=None, skewed=None):
        self.vertical: List[Dict[str, Any]] = vertical
        self.horizontal: List[Dict[str, Any]] = horizontal
        self.page_w = page_w
        self.page_h = page_h
        self.stats: Dict[str, Any] = stats
        self.all_thin_segments: List[Tuple[fitz.Point, fitz.Point]] = all_thin_segments or []
        self.skewed: List[Dict[str, Any]] = skewed or []

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<LineIndex vertical={len(self.vertical)} "
                f"horizontal={len(self.horizontal)} "
                f"skewed={len(self.skewed)} {self.stats}>")


# ---------------------------------------------------------------------------
# Segment harvesting
# ---------------------------------------------------------------------------

def _dashes_are_real(dashes: Any) -> bool:
    """
    PyMuPDF reports a dash pattern as a string like "[9 3 2 3] 0". A solid
    stroke is "[] 0" (or None). A chain line always carries a pattern.
    """
    if not dashes:
        return False
    if not isinstance(dashes, str):
        return bool(dashes)
    inner = dashes.split("]")[0].lstrip("[").strip()
    if not inner:
        return False
    try:
        return any(float(tok) > 0 for tok in inner.replace(",", " ").split())
    except ValueError:
        return False


def _iter_segments(page: "fitz.Page", rot_mat) -> Tuple[List[Dict[str, Any]], List[Tuple[fitz.Point, fitz.Point]], List[Dict[str, Any]]]:
    """
    Collect every thin straight segment on the page.
    Returns:
      (axis_aligned_segments, all_thin_segments, raw_skewed_segments)
    all_thin_segments includes non-axis-aligned segments (such as CAD diagonal
    dogleg/leader jogs connecting dodged bubbles to true grid lines).
    raw_skewed_segments includes thin segments at non-orthogonal angles.
    """
    axis_aligned: List[Dict[str, Any]] = []
    all_thin: List[Tuple[fitz.Point, fitz.Point]] = []
    raw_skewed: List[Dict[str, Any]] = []

    try:
        drawings = page.get_drawings()
    except Exception:
        return axis_aligned, all_thin, raw_skewed

    for d in drawings:
        # Stroked paths only. A filled shape is a bubble, a hatch or a solid.
        if d.get("type") not in ("s", "fs"):
            continue

        width = d.get("width")
        width = 0.0 if width is None else float(width)
        if width > MAX_STROKE_WIDTH:
            continue

        dashed = _dashes_are_real(d.get("dashes"))

        for item in d.get("items", ()):
            if not item or item[0] != "l":
                continue
            try:
                p1, p2 = item[1], item[2]
            except (IndexError, TypeError):
                continue
            if rot_mat is not None:
                p1 = p1 * rot_mat
                p2 = p2 * rot_mat

            all_thin.append((p1, p2))

            dx = abs(p2.x - p1.x)
            dy = abs(p2.y - p1.y)

            if dx <= AXIS_TOL_PTS and dy >= MIN_SEGMENT_PTS:
                axis_aligned.append({
                    "orient": "vertical",
                    "coord": (p1.x + p2.x) / 2.0,
                    "lo": min(p1.y, p2.y),
                    "hi": max(p1.y, p2.y),
                    "dashed": dashed,
                    "width": width,
                })
            elif dy <= AXIS_TOL_PTS and dx >= MIN_SEGMENT_PTS:
                axis_aligned.append({
                    "orient": "horizontal",
                    "coord": (p1.y + p2.y) / 2.0,
                    "lo": min(p1.x, p2.x),
                    "hi": max(p1.x, p2.x),
                    "dashed": dashed,
                    "width": width,
                })
            else:
                length = math.hypot(dx, dy)
                if length >= MIN_SEGMENT_PTS:
                    raw_skewed.append({
                        "p1": p1,
                        "p2": p2,
                        "length": length,
                        "dashed": dashed,
                        "width": width,
                    })

    return axis_aligned, all_thin, raw_skewed


def _cluster(segments: List[Dict[str, Any]], span_limit: float) -> List[Dict[str, Any]]:
    """
    Merge collinear segments into line candidates.

    A chain line arrives as dozens of separate dash segments, so the cluster's
    EXTENT (first lo to last hi) is what matters, not the summed ink -- a
    long dashed line has roughly half the ink of a solid one of the same reach.
    Gaps inside the extent are expected and are not split on unless the gap is
    excessive (>150pt), which prevents distant unrelated geometry (like a wall
    or beam) from merging with a tiny isolated nib near a bubble.
    """
    if not segments:
        return []

    segments = sorted(segments, key=lambda s: s["coord"])
    buckets: List[List[Dict[str, Any]]] = []

    bucket = [segments[0]]
    for seg in segments[1:]:
        if seg["coord"] - bucket[-1]["coord"] <= CLUSTER_TOL_PTS:
            bucket.append(seg)
        else:
            buckets.append(bucket)
            bucket = [seg]
    buckets.append(bucket)

    candidates: List[Dict[str, Any]] = []
    min_extent = span_limit * MIN_EXTENT_FRAC
    MAX_ALONG_LINE_GAP_PTS = 150.0

    for b in buckets:
        b_sorted = sorted(b, key=lambda s: s["lo"])
        runs: List[List[Dict[str, Any]]] = []
        cur_run = [b_sorted[0]]
        for s in b_sorted[1:]:
            gap = s["lo"] - max(x["hi"] for x in cur_run)
            if gap <= MAX_ALONG_LINE_GAP_PTS:
                cur_run.append(s)
            else:
                runs.append(cur_run)
                cur_run = [s]
        runs.append(cur_run)

        for run in runs:
            c = _fold(run)
            if (c["hi"] - c["lo"]) >= min_extent:
                candidates.append(c)

    return candidates


def _fold(bucket: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Collapse one coordinate bucket into a single candidate line."""
    ink = sum(s["hi"] - s["lo"] for s in bucket)
    # Weight the coordinate by segment length so a long run of dashes decides
    # the position, not a stray short tick that happened to land in the bucket.
    total_len = ink or 1.0
    coord = sum(s["coord"] * (s["hi"] - s["lo"]) for s in bucket) / total_len
    dashed_ink = sum(s["hi"] - s["lo"] for s in bucket if s["dashed"])
    res = {
        "orient": bucket[0]["orient"],
        "coord": coord,
        "lo": min(s["lo"] for s in bucket),
        "hi": max(s["hi"] for s in bucket),
        "ink": ink,
        "dashed": dashed_ink > (ink * 0.35),
        "segments": len(bucket),
    }
    if "angle_deg" in bucket[0]:
        res["angle_deg"] = bucket[0]["angle_deg"]
    return res


def _cluster_skewed(raw_skewed: List[Dict[str, Any]], span_limit: float) -> List[Dict[str, Any]]:
    """Group non-orthogonal segments by dominant angles and cluster into chain lines."""
    if not raw_skewed:
        return []

    angle_bins = defaultdict(lambda: {"count": 0, "ink": 0.0, "segs": []})
    for s in raw_skewed:
        p1, p2 = s["p1"], s["p2"]
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        length = s["length"]
        angle = math.degrees(math.atan2(dy, dx)) % 180.0
        # Exclude near-horizontal and near-vertical
        if angle < 1.5 or angle > 178.5 or abs(angle - 90.0) < 1.5:
            continue

        b = round(angle)
        angle_bins[b]["count"] += 1
        angle_bins[b]["ink"] += length
        angle_bins[b]["segs"].append((angle, length, s))

    # Identify dominant angles with significant presence
    sorted_bins = sorted(angle_bins.items(), key=lambda x: -x[1]["ink"])
    used_bins = set()
    dominant_angles = []

    for b, data in sorted_bins:
        if b in used_bins:
            continue
        if data["count"] >= 6 and data["ink"] >= 100.0:
            cluster_segs = list(data["segs"])
            used_bins.add(b)
            for adj in (b - 1, b + 1):
                if adj in angle_bins and adj not in used_bins:
                    cluster_segs.extend(angle_bins[adj]["segs"])
                    used_bins.add(adj)
            weighted_angle = sum(x[0] * x[1] for x in cluster_segs) / sum(x[1] for x in cluster_segs)
            dominant_angles.append((round(weighted_angle, 2), cluster_segs))

    all_candidates = []
    for dom_angle, dom_segs in dominant_angles:
        rad = math.radians(dom_angle)
        sin_a = math.sin(rad)
        cos_a = math.cos(rad)

        clust_segs = []
        for _, _, s in dom_segs:
            p1, p2 = s["p1"], s["p2"]
            s1 = p1.x * cos_a + p1.y * sin_a
            s2 = p2.x * cos_a + p2.y * sin_a
            d1 = -p1.x * sin_a + p1.y * cos_a
            d2 = -p2.x * sin_a + p2.y * cos_a
            clust_segs.append({
                "orient": "skewed",
                "angle_deg": dom_angle,
                "coord": (d1 + d2) / 2.0,
                "lo": min(s1, s2),
                "hi": max(s1, s2),
                "dashed": s["dashed"],
                "width": s["width"],
            })

        lines = _cluster(clust_segs, span_limit)
        all_candidates.extend(lines)

    return all_candidates


def build_line_index(page: "fitz.Page", page_w: float, page_h: float,
                     rot_mat=None) -> LineIndex:
    """
    Recover candidate chain lines for both axes and skewed angles.
    """
    segments, all_thin, raw_skewed = _iter_segments(page, rot_mat)

    vertical = _cluster([s for s in segments if s["orient"] == "vertical"], page_h)
    horizontal = _cluster([s for s in segments if s["orient"] == "horizontal"], page_w)
    skewed = _cluster_skewed(raw_skewed, max(page_w, page_h))

    stats = {
        "segments_total": len(segments),
        "vertical_candidates": len(vertical),
        "horizontal_candidates": len(horizontal),
        "skewed_candidates": len(skewed),
        "dashed_vertical": sum(1 for c in vertical if c["dashed"]),
        "dashed_horizontal": sum(1 for c in horizontal if c["dashed"]),
        "dashed_skewed": sum(1 for c in skewed if c.get("dashed")),
    }
    return LineIndex(vertical, horizontal, page_w, page_h, stats, all_thin, skewed=skewed)


# ---------------------------------------------------------------------------
# Bubble -> line matching
# ---------------------------------------------------------------------------

def trace_bubble_leader_target(
    cx: float,
    cy: float,
    orient: str,
    candidates: List[Dict[str, Any]],
    all_thin_segments: List[Tuple[fitz.Point, fitz.Point]],
    bubble_radius: float = 12.0,
) -> Optional[Tuple[Dict[str, Any], float]]:
    """
    Traces CAD leader / dogleg paths starting at/near the bubble circumference
    to determine which candidate grid line the bubble physically connects to.

    When sub-grids are dodged sideways to prevent bubble overlap, drafters draw
    a leader stem from the bubble circle and a diagonal dogleg jog connecting
    directly into the true grid line. Tracing these connected vector segments
    recovers the exact grid line with zero ambiguity.

    Returns (candidate_line, offset_delta) if a connected leader path terminates
    at a candidate line, else None.
    """
    if not all_thin_segments or not candidates:
        return None

    bubble_radius = bubble_radius or 16.0
    # Search window near circumference: bubble radius is typically 12-22 pt,
    # and leader segments start at the circle boundary.
    max_start_dist = max(bubble_radius + 6.0, 25.0)

    queue = []
    visited = set()
    for idx, (p1, p2) in enumerate(all_thin_segments):
        d1 = math.hypot(p1.x - cx, p1.y - cy)
        d2 = math.hypot(p2.x - cx, p2.y - cy)
        if min(d1, d2) <= max_start_dist:
            start_pt = p1 if d1 < d2 else p2
            end_pt = p2 if d1 < d2 else p1
            queue.append((end_pt, [start_pt, end_pt], idx))
            visited.add(idx)

    if not queue:
        return None

    # Breadth-first search up to 6 hops
    hit_candidates = []
    for hop in range(6):
        next_queue = []
        for curr_pt, path, last_idx in queue:
            # Check if curr_pt aligns with any candidate line
            for c in candidates:
                if orient == "vertical":
                    if abs(curr_pt.x - c["coord"]) <= 2.0 and (c["lo"] - 12.0 <= curr_pt.y <= c["hi"] + 12.0):
                        hit_candidates.append((c, hop, len(path)))
                else:
                    if abs(curr_pt.y - c["coord"]) <= 2.0 and (c["lo"] - 12.0 <= curr_pt.x <= c["hi"] + 12.0):
                        hit_candidates.append((c, hop, len(path)))

            for idx, (p1, p2) in enumerate(all_thin_segments):
                if idx in visited:
                    continue
                d1 = math.hypot(p1.x - curr_pt.x, p1.y - curr_pt.y)
                d2 = math.hypot(p2.x - curr_pt.x, p2.y - curr_pt.y)
                if d1 <= 3.5:
                    next_queue.append((p2, path + [p2], idx))
                    visited.add(idx)
                elif d2 <= 3.5:
                    next_queue.append((p1, path + [p1], idx))
                    visited.add(idx)

        queue = next_queue
        if hit_candidates or not queue:
            break

    if not hit_candidates:
        return None

    # Best hit: lowest hops, then longest candidate line / most segments
    hit_candidates.sort(key=lambda item: (item[1], -item[0].get("segments", 0), -item[0].get("ink", 0)))
    best_candidate = hit_candidates[0][0]
    delta = abs(best_candidate["coord"] - (cx if orient == "vertical" else cy))
    return best_candidate, delta


def _best_line(candidates: List[Dict[str, Any]], across: float, along: float
               ) -> Optional[Tuple[Dict[str, Any], float, float]]:
    """
    Pick the line this bubble terminates.

    `across` is the bubble's coordinate perpendicular to the line (the bubble's
    x for a vertical line, y for a horizontal line); `along` is its coordinate
    parallel to the line.

    Returns (line_dict, delta_pts, runner_up_margin_pts) or None.
    delta_pts is the absolute offset between bubble centre and line coordinate.
    runner_up_margin_pts is how much better the chosen line scored than the
    second-best candidate: infinite when only one candidate was within
    tolerance, small when two candidates scored almost equally.
    """
    best: Optional[Tuple[Dict[str, Any], float]] = None
    best_cost: Optional[float] = None
    best_coord: Optional[float] = None

    for c in candidates:
        delta = abs(c["coord"] - across)
        if delta > BUBBLE_TO_LINE_TOL_PTS:
            continue

        # Distance from the bubble to the line's extent, along the line. Zero
        # when the bubble sits within the run (interior bubble); small when it
        # sits just past the end (the normal margin case).
        if along < c["lo"]:
            end_gap = c["lo"] - along
        elif along > c["hi"]:
            end_gap = along - c["hi"]
        else:
            end_gap = 0.0

        if end_gap > LINE_END_TO_BUBBLE_TOL_PTS:
            continue

        cost = delta + end_gap * 0.25
        if c["dashed"]:
            cost -= DASH_BONUS_PTS
        if c.get("segments", 0) >= SEGMENT_CHAIN_MIN:
            cost -= SEGMENT_CHAIN_BONUS_PTS
        # Prefer the longer line when two are otherwise equal -- a primary grid
        # running the full plan beats a short fragment sharing its coordinate.
        cost -= min(c["hi"] - c["lo"], 400.0) * 0.004

        if best_cost is None or cost < best_cost:
            best_cost = cost
            best = (c, delta)
            best_coord = c["coord"]

    if best is None:
        return None

    # Compute runner-up cost only against DIFFERENT physical lines (ignore
    # parallel strokes / double lines within 3.5pt of the winning line).
    SAME_LINE_TOL_PTS = 3.5
    runner_up_cost = None
    best_is_major = (best[0].get("segments", 0) >= 6 or (best[0]["hi"] - best[0]["lo"]) >= 350.0 or best[0].get("dashed", False))
    for c in candidates:
        if abs(c["coord"] - best_coord) <= SAME_LINE_TOL_PTS:
            continue
        # A minor interior framing fragment (e.g. 1-2 segments, short length)
        # cannot compete as a runner-up against a major multi-segment building chain line.
        if best_is_major and c.get("segments", 0) < 3 and (c["hi"] - c["lo"]) < 300.0 and not c.get("dashed"):
            continue
        delta = abs(c["coord"] - across)
        if delta > BUBBLE_TO_LINE_TOL_PTS:
            continue

        if along < c["lo"]:
            end_gap = c["lo"] - along
        elif along > c["hi"]:
            end_gap = along - c["hi"]
        else:
            end_gap = 0.0

        if end_gap > LINE_END_TO_BUBBLE_TOL_PTS:
            continue

        cost = delta + end_gap * 0.25
        if c["dashed"]:
            cost -= DASH_BONUS_PTS
        if c.get("segments", 0) >= SEGMENT_CHAIN_MIN:
            cost -= SEGMENT_CHAIN_BONUS_PTS
        cost -= min(c["hi"] - c["lo"], 400.0) * 0.004

        if runner_up_cost is None or cost < runner_up_cost:
            runner_up_cost = cost

    line, delta = best
    margin = float("inf") if runner_up_cost is None else (runner_up_cost - best_cost)
    return line, delta, margin


def attach_line_coords(confirmed: List[Dict[str, Any]], line_index: LineIndex) -> Dict[str, Any]:
    """
    For every confirmed bubble, attach the coordinate of the chain line it
    terminates, on both axes. Mutates the dicts in place and returns a summary.

    Both axes are attached because the caller does not yet know which label
    family runs which way -- `_build_axis_tracks` decides that afterwards by
    scoring both orientations, and then reads whichever of line_cx / line_cy
    matches its pos_key.
    """
    matched_x = matched_y = 0
    deltas: List[float] = []

    for c in confirmed:
        cx, cy = c["cx"], c["cy"]
        r = c.get("r") or 16.0

        # Try leader tracing first for vertical chain lines
        leader_v = trace_bubble_leader_target(
            cx, cy, "vertical", line_index.vertical, line_index.all_thin_segments, r
        )
        if leader_v is not None:
            line, delta = leader_v
            c["line_cx"] = round(line["coord"], 3)
            c["line_cx_source"] = "vector_line"
            c["line_cx_delta"] = round(delta, 2)
            c["line_cx_dashed"] = line["dashed"]
            c["line_cx_len_frac"] = round((line["hi"] - line["lo"]) / max(line_index.page_h, 1.0), 3)
            c["line_cx_margin"] = float("inf")
            c["line_cx_is_leader"] = True
            c["line_cx_segments"] = line.get("segments", 1)
            matched_x += 1
            deltas.append(delta)
        else:
            hit_v = _best_line(line_index.vertical, across=cx, along=cy)
            if hit_v is not None:
                line, delta, margin = hit_v
                c["line_cx"] = round(line["coord"], 3)
                c["line_cx_source"] = "vector_line"
                c["line_cx_delta"] = round(delta, 2)
                c["line_cx_dashed"] = line["dashed"]
                c["line_cx_len_frac"] = round((line["hi"] - line["lo"]) / max(line_index.page_h, 1.0), 3)
                c["line_cx_margin"] = None if margin == float("inf") else round(margin, 2)
                c["line_cx_is_leader"] = False
                c["line_cx_segments"] = line.get("segments", 1)
                matched_x += 1
                deltas.append(delta)
            else:
                c["line_cx"] = None
                c["line_cx_source"] = "bubble_inferred"
                c["line_cx_delta"] = None
                c["line_cx_dashed"] = None
                c["line_cx_len_frac"] = None
                c["line_cx_margin"] = None
                c["line_cx_is_leader"] = False
                c["line_cx_segments"] = 0

        # Try leader tracing first for horizontal chain lines
        leader_h = trace_bubble_leader_target(
            cx, cy, "horizontal", line_index.horizontal, line_index.all_thin_segments, r
        )
        if leader_h is not None:
            line, delta = leader_h
            c["line_cy"] = round(line["coord"], 3)
            c["line_cy_source"] = "vector_line"
            c["line_cy_delta"] = round(delta, 2)
            c["line_cy_dashed"] = line["dashed"]
            c["line_cy_len_frac"] = round((line["hi"] - line["lo"]) / max(line_index.page_w, 1.0), 3)
            c["line_cy_margin"] = float("inf")
            c["line_cy_is_leader"] = True
            c["line_cy_segments"] = line.get("segments", 1)
            matched_y += 1
            deltas.append(delta)
        else:
            hit_h = _best_line(line_index.horizontal, across=cy, along=cx)
            if hit_h is not None:
                line, delta, margin = hit_h
                c["line_cy"] = round(line["coord"], 3)
                c["line_cy_source"] = "vector_line"
                c["line_cy_delta"] = round(delta, 2)
                c["line_cy_dashed"] = line["dashed"]
                c["line_cy_len_frac"] = round((line["hi"] - line["lo"]) / max(line_index.page_w, 1.0), 3)
                c["line_cy_margin"] = None if margin == float("inf") else round(margin, 2)
                c["line_cy_is_leader"] = False
                c["line_cy_segments"] = line.get("segments", 1)
                matched_y += 1
                deltas.append(delta)
            else:
                c["line_cy"] = None
                c["line_cy_source"] = "bubble_inferred"
                c["line_cy_delta"] = None
                c["line_cy_dashed"] = None
                c["line_cy_len_frac"] = None
                c["line_cy_margin"] = None
                c["line_cy_is_leader"] = False
                c["line_cy_segments"] = 0

        # Check candidate skewed chain lines
        c["line_skewed"] = None
        if line_index.skewed:
            best_skewed_hit = None
            best_skewed_cost = None
            by_angle = {}
            for l in line_index.skewed:
                by_angle.setdefault(l.get("angle_deg", 0.0), []).append(l)
            for angle_deg, cands in by_angle.items():
                rad = math.radians(angle_deg)
                sin_a = math.sin(rad)
                cos_a = math.cos(rad)
                d = -cx * sin_a + cy * cos_a
                s = cx * cos_a + cy * sin_a
                hit = _best_line(cands, across=d, along=s)
                if hit is not None:
                    line, delta, margin = hit
                    cost = delta
                    if best_skewed_cost is None or cost < best_skewed_cost:
                        best_skewed_cost = cost
                        x_line = s * cos_a - line["coord"] * sin_a
                        y_line = s * sin_a + line["coord"] * cos_a
                        best_skewed_hit = {
                            "angle_deg": angle_deg,
                            "line_coord": round(line["coord"], 3),
                            "line_cx": round(x_line, 3),
                            "line_cy": round(y_line, 3),
                            "offset_pts": round(delta, 2),
                            "dashed": line.get("dashed", False),
                            "segments": line.get("segments", 1),
                            "source": "vector_line",
                        }
            if best_skewed_hit is not None:
                c["line_skewed"] = best_skewed_hit

    total = len(confirmed) or 1
    deltas_sorted = sorted(deltas)
    return {
        "bubbles": len(confirmed),
        "matched_vertical_line": matched_x,
        "matched_horizontal_line": matched_y,
        "match_rate_vertical": round(matched_x / total, 3),
        "match_rate_horizontal": round(matched_y / total, 3),
        "median_offset_pts": round(deltas_sorted[len(deltas_sorted) // 2], 2) if deltas_sorted else None,
        "max_offset_pts": round(deltas_sorted[-1], 2) if deltas_sorted else None,
    }


def grid_coord(bubble: Dict[str, Any], pos_key: str) -> Tuple[float, str]:
    """
    The coordinate to measure from, and where it came from.

    pos_key is "cx" for a grid whose LINE runs vertically (bubbles on the top
    and bottom rails), "cy" for one whose line runs horizontally. Returns the
    vector line's coordinate when one was matched, otherwise the bubble centre
    -- never None, so no caller has to branch on availability.
    """
    line_key = "line_cx" if pos_key == "cx" else "line_cy"
    value = bubble.get(line_key)
    if value is not None:
        return float(value), "vector_line"
    return float(bubble[pos_key]), "bubble_inferred"


def line_evidence(bubble: Dict[str, Any], pos_key: str) -> Tuple[Optional[float], Optional[float]]:
    """(length fraction, margin over runner-up) for this bubble's matched line."""
    if pos_key == "cx":
        return bubble.get("line_cx_len_frac"), bubble.get("line_cx_margin")
    return bubble.get("line_cy_len_frac"), bubble.get("line_cy_margin")


def reject_outlier_line_coords(chain_entries: List[Dict[str, Any]]) -> int:
    """
    Decide, per grid, whether the line or the bubble is the better coordinate,
    and report how many line matches were not taken.

    Three bands, using the axis's own median bay spacing as the yardstick:

      * agree   -- the line sits within a hair of the bubble. Nothing was
                   dodged; the bubble is already exact and this module's
                   matching noise is the only thing a swap would add. Keep the
                   bubble, marked "bubble_confirmed_by_line" -- the strongest
                   state there is, because two independent sources agree.
      * correct -- the line sits meaningfully away from the bubble. The bubble
                   was dodged to make room; the line is the real grid. Take it.
      * reject  -- the line moved the grid by more than a quarter of a bay.
                   That is not a dodge, it is a mis-match against unrelated
                   geometry. Keep the bubble, marked so a reader can tell this
                   apart from "no line was found at all".

    IMPORTANT for sub-grids (secondary labels like B.6, C.1, 7.1 etc.):
    Sub-grids are inserted into the tightest bays — that is precisely WHY
    the drafter dodges them the most. Using the whole-track median bay as
    the outlier ceiling incorrectly rejects legitimate line corrections on
    sub-grids. For a secondary entry, we use the smaller of:
      (a) the whole-track median bay  (the global reference)
      (b) the minimum of the two bays immediately adjacent to this entry
    This makes the outlier ceiling proportional to the SUB-GRID's own bay
    rather than the global median, which for a primary-heavy track can be
    3-5x larger than a real sub-bay.

    Call this once a track's chain exists, because only then is the axis's own
    typical bay spacing known. Matching happens per-bubble against the whole
    page, so a stray label that passed the circle-plus-text bubble test can
    latch onto an unrelated long line; on a real sheet those strays are
    dropped by the track builder anyway, but a mis-match on a bubble that IS
    in the chain would silently corrupt two bays. A grid that moved by more
    than a quarter of the reference bay did not get dodged -- it got mismatched.

    Mutates entries in place. Reverted entries are marked
    coord_source="bubble_inferred_outlier" so a reader can tell the difference
    between "no line was found" and "a line was found and rejected".
    """
    if len(chain_entries) < 3:
        return 0

    bubble_coords = [e.get("bubble_coord") for e in chain_entries]
    if any(b is None for b in bubble_coords):
        return 0

    ordered = sorted(bubble_coords)
    spans = [b - a for a, b in zip(ordered, ordered[1:]) if (b - a) > 1.0]
    if not spans:
        return 0
    median_span = sorted(spans)[len(spans) // 2]
    global_outlier_limit = median_span * OUTLIER_FRAC_OF_MEDIAN_BAY
    agree_band = max(AGREE_BAND_FLOOR_PTS,
                     median_span * AGREE_BAND_FRAC_OF_MEDIAN_BAY)

    reverted = 0
    for e in chain_entries:
        if e.get("coord_source") != "vector_line":
            continue
        off = e.get("bubble_offset_pts")
        if off is None:
            continue
        is_secondary = e.get("is_secondary", False)

        if off <= agree_band:
            if not is_secondary:
                e["coord"] = e["bubble_coord"]
            e["coord_source"] = "bubble_confirmed_by_line"
            continue

        # If the grid line is explicitly connected to the bubble via a traced CAD leader / dogleg,
        # it is ground truth: never revert it to the offset bubble coordinate.
        if e.get("is_leader_verified"):
            continue

        # ── Outlier rejection gate ────────────────────────────────────────────
        # PRIMARY grids: reject if the line moved the coord by > 25% of the
        # track's median bay (this is a mismatch against unrelated geometry).
        #
        # SECONDARY grids (B.6, C.1, 7.1 ...): DO NOT apply the global median-bay
        # ceiling. Sub-grids are inserted into the TIGHTEST bays and their
        # bubbles are dodged the MOST — that is the entire point of this code.
        # The median bay of the track is dominated by primary spans that are
        # 3-5x larger than a real sub-bay, making the 25% ceiling absurdly tight
        # for secondaries. For example: median primary bay = 200 pt, outlier
        # limit = 50 pt, but the drafter routinely dodges sub-grid bubbles by
        # 40-80 pt. Applying the primary threshold falsely reverts these and
        # produces wrong dimensions — exactly the bug seen on screen.
        # Secondaries are controlled exclusively by the line-quality gate below.
        if not is_secondary and off > global_outlier_limit:
            e["coord"] = e["bubble_coord"]
            e["coord_source"] = "bubble_inferred_outlier"
            e["rejected_line_offset_pts"] = off
            e["bubble_offset_pts"] = None
            reverted += 1
            continue

        # ── Line-quality gate ─────────────────────────────────────────────────
        # Override the bubble only when the matched line is long enough and
        # unambiguous enough to be trusted.
        len_frac = e.get("line_len_frac")
        margin = e.get("line_margin")
        seg_count = e.get("line_segments", 0)

        if is_secondary:
            # Sub-grid chain lines genuinely run only part of the plan extent by
            # definition (they terminate at the parent grid or local bays, ~100-250pt).
            # Accept if length fraction >= 0.035 and either margin >= 2.0 pt, length fraction >= 0.20,
            # or line has multiple chain segments (>= 4).
            strong = (len_frac is not None and len_frac >= 0.035
                      and (margin is None or margin >= 2.0 or len_frac >= 0.20 or seg_count >= 4))
        else:
            # Primary grids can also be dodged sideways when placed adjacent to a
            # sub-grid. Accept if line is long enough (>= MIN_CORRECT_LEN_FRAC),
            # or has multiple chain segments (>= 4), and is unambiguous (margin >= 2.0 or None).
            strong = (len_frac is not None
                      and (len_frac >= MIN_CORRECT_LEN_FRAC or seg_count >= 4)
                      and (margin is None or margin >= MIN_CORRECT_MARGIN_PTS))

        if not strong:
            e["coord"] = e["bubble_coord"]
            e["coord_source"] = "bubble_kept_weak_line"
            e["rejected_line_offset_pts"] = off
            e["bubble_offset_pts"] = None
            reverted += 1
        # else: leave coord on the line -- a real dodge, corrected.
    return reverted


def chain_offset_report(chain_entries: List[Dict[str, Any]],
                        pts_per_foot: float) -> List[Dict[str, Any]]:
    """
    How far each ACCEPTED grid's bubble sat from its own line, worst first.

    This is the honest measure of what the old bubble-centre rule was costing,
    because it only counts grids that survived into a real dimension track --
    unlike offset_report() below, which sees every confirmed bubble on the
    page including the strays the track builder later discards.
    """
    rows = []
    for e in chain_entries:
        off = e.get("bubble_offset_pts")
        if off is None or pts_per_foot <= 0:
            continue
        rows.append({
            "label": e.get("label"),
            "offset_pts": off,
            "offset_inches": round(off / pts_per_foot * 12.0, 1),
        })
    rows.sort(key=lambda r: -r["offset_pts"])
    return rows


def offset_report(confirmed: List[Dict[str, Any]], pos_key: str,
                  pts_per_foot: float) -> List[Dict[str, Any]]:
    """
    Every bubble that sat measurably off its own line, worst first, in feet.

    This is the diagnostic that shows what the old bubble-centre measurement
    was actually costing on a given sheet: each entry is an error that was
    previously folded silently into the two bays either side of that grid.
    """
    delta_key = "line_cx_delta" if pos_key == "cx" else "line_cy_delta"
    rows = []
    for c in confirmed:
        d = c.get(delta_key)
        if d is None or pts_per_foot <= 0:
            continue
        rows.append({
            "label": c.get("text"),
            "offset_pts": d,
            "offset_ft": round(d / pts_per_foot, 3),
            "offset_inches": round(d / pts_per_foot * 12.0, 1),
        })
    rows.sort(key=lambda r: -r["offset_pts"])
    return rows
