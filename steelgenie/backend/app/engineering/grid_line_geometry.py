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
# direction. Sub-grids terminate early, hence the low bar; the bubble-proximity
# test below is what actually does the discriminating.
MIN_EXTENT_FRAC = 0.16

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
MIN_CORRECT_LEN_FRAC = 0.50
MIN_CORRECT_MARGIN_PTS = 6.0

# Safety net for a bubble that matched the wrong line. Applied after a track's
# chain exists, when the axis's own typical bay spacing is finally known: a
# line-derived coordinate that moved the grid by more than this fraction of the
# median bay is not a drafter's dodge, it is a mis-match, and the bubble
# coordinate is restored. Deliberately loose -- it exists to catch gross
# errors, not to second-guess ordinary dodges.
OUTLIER_FRAC_OF_MEDIAN_BAY = 0.25


class LineIndex:
    """Axis-aligned candidate chain lines recovered from a page's vector paths."""

    __slots__ = ("vertical", "horizontal", "page_w", "page_h", "stats")

    def __init__(self, vertical, horizontal, page_w, page_h, stats):
        self.vertical: List[Dict[str, Any]] = vertical
        self.horizontal: List[Dict[str, Any]] = horizontal
        self.page_w = page_w
        self.page_h = page_h
        self.stats: Dict[str, Any] = stats

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<LineIndex vertical={len(self.vertical)} "
                f"horizontal={len(self.horizontal)} {self.stats}>")


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


def _iter_segments(page: "fitz.Page", rot_mat) -> List[Dict[str, Any]]:
    """
    Collect every thin, axis-aligned straight segment on the page, tagged with
    whether its stroke was dashed. Curves, fills and heavy strokes are skipped.
    """
    segments: List[Dict[str, Any]] = []

    try:
        drawings = page.get_drawings()
    except Exception:
        return segments

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

            dx = abs(p2.x - p1.x)
            dy = abs(p2.y - p1.y)

            if dx <= AXIS_TOL_PTS and dy >= MIN_SEGMENT_PTS:
                segments.append({
                    "orient": "vertical",
                    "coord": (p1.x + p2.x) / 2.0,
                    "lo": min(p1.y, p2.y),
                    "hi": max(p1.y, p2.y),
                    "dashed": dashed,
                    "width": width,
                })
            elif dy <= AXIS_TOL_PTS and dx >= MIN_SEGMENT_PTS:
                segments.append({
                    "orient": "horizontal",
                    "coord": (p1.y + p2.y) / 2.0,
                    "lo": min(p1.x, p2.x),
                    "hi": max(p1.x, p2.x),
                    "dashed": dashed,
                    "width": width,
                })

    return segments


def _cluster(segments: List[Dict[str, Any]], span_limit: float) -> List[Dict[str, Any]]:
    """
    Merge collinear segments into line candidates.

    A chain line arrives as dozens of separate dash segments, so the cluster's
    EXTENT (first lo to last hi) is what matters, not the summed ink -- a
    long dashed line has roughly half the ink of a solid one of the same reach.
    Gaps inside the extent are expected and are not split on: a grid line
    passing behind a column bubble or a block of text is interrupted in the
    vector stream but is one line.
    """
    if not segments:
        return []

    segments = sorted(segments, key=lambda s: s["coord"])
    candidates: List[Dict[str, Any]] = []

    bucket = [segments[0]]
    for seg in segments[1:]:
        if seg["coord"] - bucket[-1]["coord"] <= CLUSTER_TOL_PTS:
            bucket.append(seg)
        else:
            candidates.append(_fold(bucket))
            bucket = [seg]
    candidates.append(_fold(bucket))

    min_extent = span_limit * MIN_EXTENT_FRAC
    return [c for c in candidates if (c["hi"] - c["lo"]) >= min_extent]


def _fold(bucket: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Collapse one coordinate bucket into a single candidate line."""
    ink = sum(s["hi"] - s["lo"] for s in bucket)
    # Weight the coordinate by segment length so a long run of dashes decides
    # the position, not a stray short tick that happened to land in the bucket.
    total_len = ink or 1.0
    coord = sum(s["coord"] * (s["hi"] - s["lo"]) for s in bucket) / total_len
    dashed_ink = sum(s["hi"] - s["lo"] for s in bucket if s["dashed"])
    return {
        "orient": bucket[0]["orient"],
        "coord": coord,
        "lo": min(s["lo"] for s in bucket),
        "hi": max(s["hi"] for s in bucket),
        "ink": ink,
        "dashed": dashed_ink > (ink * 0.35),
        "segments": len(bucket),
    }


def build_line_index(page: "fitz.Page", page_w: float, page_h: float,
                     rot_mat=None) -> LineIndex:
    """
    Recover candidate chain lines for both axes.

    page_w / page_h must already be in the sheet's DISPLAYED orientation --
    i.e. swapped for a 90/270-rotated page, exactly as
    run_deterministic_geometry_pass computes them -- and rot_mat must be the
    same page.rotation_matrix passed to _find_confirmed_bubbles, so line
    coordinates land in the same space as bubble coordinates.
    """
    segments = _iter_segments(page, rot_mat)

    vertical = _cluster([s for s in segments if s["orient"] == "vertical"], page_h)
    horizontal = _cluster([s for s in segments if s["orient"] == "horizontal"], page_w)

    stats = {
        "segments_total": len(segments),
        "vertical_candidates": len(vertical),
        "horizontal_candidates": len(horizontal),
        "dashed_vertical": sum(1 for c in vertical if c["dashed"]),
        "dashed_horizontal": sum(1 for c in horizontal if c["dashed"]),
    }
    return LineIndex(vertical, horizontal, page_w, page_h, stats)


# ---------------------------------------------------------------------------
# Bubble -> line matching
# ---------------------------------------------------------------------------

def _best_line(candidates: List[Dict[str, Any]], across: float, along: float
               ) -> Optional[Tuple[Dict[str, Any], float]]:
    """
    Pick the line this bubble terminates.

    `across` is the bubble's coordinate perpendicular to the line (the bubble's
    cx for a vertical line); `along` is its coordinate parallel to the line
    (cy for a vertical line), used to check the line actually reaches the
    bubble instead of being a different grid that merely passes nearby.

    Returns (line, delta, margin) -- delta is the magnitude of the offset
    between bubble and line, margin is how much the runner-up candidate lost
    by (inf when there was no runner-up). A small margin means the match was
    a coin flip and must not be trusted to override the bubble. Returns None
    when nothing qualifies.
    """
    best = None
    best_cost = None
    second_cost = None

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
            second_cost = best_cost
            best_cost = cost
            best = (c, delta)
        elif second_cost is None or cost < second_cost:
            second_cost = cost

    if best is None:
        return None
    line, delta = best
    margin = float("inf") if second_cost is None else (second_cost - best_cost)
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

        hit_v = _best_line(line_index.vertical, across=cx, along=cy)
        if hit_v is not None:
            line, delta, margin = hit_v
            c["line_cx"] = round(line["coord"], 3)
            c["line_cx_source"] = "vector_line"
            c["line_cx_delta"] = round(delta, 2)
            c["line_cx_dashed"] = line["dashed"]
            c["line_cx_len_frac"] = round((line["hi"] - line["lo"]) / max(line_index.page_h, 1.0), 3)
            c["line_cx_margin"] = None if margin == float("inf") else round(margin, 2)
            matched_x += 1
            deltas.append(delta)
        else:
            c["line_cx"] = None
            c["line_cx_source"] = "bubble_inferred"
            c["line_cx_delta"] = None
            c["line_cx_dashed"] = None
            c["line_cx_len_frac"] = None
            c["line_cx_margin"] = None

        hit_h = _best_line(line_index.horizontal, across=cy, along=cx)
        if hit_h is not None:
            line, delta, margin = hit_h
            c["line_cy"] = round(line["coord"], 3)
            c["line_cy_source"] = "vector_line"
            c["line_cy_delta"] = round(delta, 2)
            c["line_cy_dashed"] = line["dashed"]
            c["line_cy_len_frac"] = round((line["hi"] - line["lo"]) / max(line_index.page_w, 1.0), 3)
            c["line_cy_margin"] = None if margin == float("inf") else round(margin, 2)
            matched_y += 1
            deltas.append(delta)
        else:
            c["line_cy"] = None
            c["line_cy_source"] = "bubble_inferred"
            c["line_cy_delta"] = None
            c["line_cy_dashed"] = None
            c["line_cy_len_frac"] = None
            c["line_cy_margin"] = None

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

    Call this once a track's chain exists, because only then is the axis's own
    typical bay spacing known. Matching happens per-bubble against the whole
    page, so a stray label that passed the circle-plus-text bubble test can
    latch onto an unrelated long line; on a real sheet those strays are
    dropped by the track builder anyway, but a mis-match on a bubble that IS
    in the chain would silently corrupt two bays. A grid that moved by more
    than a quarter of the median bay did not get dodged -- it got mismatched.

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
    outlier_limit = median_span * OUTLIER_FRAC_OF_MEDIAN_BAY
    agree_band = max(AGREE_BAND_FLOOR_PTS,
                     median_span * AGREE_BAND_FRAC_OF_MEDIAN_BAY)

    reverted = 0
    for e in chain_entries:
        if e.get("coord_source") != "vector_line":
            continue
        off = e.get("bubble_offset_pts")
        if off is None:
            continue
        if off <= agree_band:
            e["coord"] = e["bubble_coord"]
            e["coord_source"] = "bubble_confirmed_by_line"
            continue
        if off > outlier_limit:
            e["coord"] = e["bubble_coord"]
            e["coord_source"] = "bubble_inferred_outlier"
            e["rejected_line_offset_pts"] = off
            e["bubble_offset_pts"] = None
            reverted += 1
            continue
        # Outside the dead band: override the bubble only on strong evidence.
        len_frac = e.get("line_len_frac")
        margin = e.get("line_margin")
        strong = (len_frac is not None and len_frac >= MIN_CORRECT_LEN_FRAC
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
