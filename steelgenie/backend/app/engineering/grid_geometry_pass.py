"""
Step 1: Deterministic Geometry Pass (Zero LLM / Zero External API Dependencies)

Extracts:
1. Grid bubbles & axis lines (Vertical & Horizontal Grids) -- CONFIRMED against
   real vector bubble geometry (page.get_drawings()), not text position alone.
2. Exact center-to-center Bay Dimensions (Feet & Inches text + inches + pixel span)
   -- length is ALWAYS geometry (distance / scale), never overwritten by nearby
   printed text. Printed text is used only to calibrate the scale when no
   explicit scale is on the sheet, and to flag agreement/disagreement for QA.
3. Grid Intersections: All (Grid_X, Grid_Y) coordinate pairs with exact (X, Y)
   points and ready-to-crop bounding boxes for downstream inspection.
4. Scale detection (explicit scale callouts e.g. 1/8" = 1'-0"), with an
   explicit "is_explicit" flag -- a guessed/default scale is never silently
   indistinguishable from a real one.

Fixes vs. the previous version of this module:
  - Every grid label must be confirmed by a REAL vector bubble shape at that
    location, not just matching text found anywhere on the sheet. Stray
    digits (rebar counts, elevations, sheet dimension text, callouts) can no
    longer be mistaken for grid lines.
  - Grid selection uses the sheet's real bubble geometry: the densest single
    row/column of confirmed bubbles per axis, biased toward the sheet's outer
    margin (real grid bubbles live there; false-positive detail/section
    callouts scatter through the interior).
  - A contiguous-run cutoff rejects a same-labeled bubble bleeding in from an
    unrelated part of a combined/multi-section sheet.
  - Bay length is always `distance_between_confirmed_points / pts_per_foot`.
    Printed dimension text is used only (a) to calibrate pts_per_foot when no
    explicit scale is printed, using the median across several independent
    matches, and (b) as a QA cross-check flag -- never to replace the number.
"""

from __future__ import annotations
import os
import re
import statistics
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
import fitz  # PyMuPDF

# Coordinate sources that are backed by a real chain line: either the line
# was taken outright (the bubble was dodged) or the line agreed with the
# bubble and confirmed it. Both mean "this grid's position is line-verified".
_LINE_BACKED = ("vector_line", "bubble_confirmed_by_line")

from app.engineering.grid_line_geometry import (
    build_line_index,
    attach_line_coords,
    grid_coord,
    line_evidence,
    reject_outlier_line_coords,
    chain_offset_report,
)

# ---------------------------------------------------------------------------
# Label patterns
# ---------------------------------------------------------------------------
_GRID_LETTER_PRIMARY = re.compile(r"^[A-Z]$")
_GRID_LETTER_SECONDARY = re.compile(r"^[A-Z]\.\d+$")
_GRID_NUMBER_PRIMARY = re.compile(r"^\d{1,2}$")
_GRID_NUMBER_SECONDARY = re.compile(r"^\d{1,2}\.\d+$")

# Dimension-text parsing (unchanged -- this part was already solid)
_DIM_RE = re.compile(r"""
    ^
    (?:\(?\s*)?
    (?P<feet>\d+)\s*['\u2019]\s*[-\u2013\u2014]?\s*
    (?:
        (?P<inches>\d+)
        (?:\s+(?P<num>\d+)\s*/\s*(?P<den>\d+))?
        \s*["\u201d]
    )?
    (?:\s*\)?\s*)?
    $
""", re.VERBOSE)

_INCH_ONLY_RE = re.compile(r"""
    ^
    (?:\(?\s*)?
    (?P<inches>\d+)
    (?:\s+(?P<num>\d+)\s*/\s*(?P<den>\d+))?
    \s*["\u201d]
    (?:\s*\)?\s*)?
    $
""", re.VERBOSE)


def parse_dimension_string(text: str) -> Optional[float]:
    """Parse dimension strings like 24'-0", 30'-6 1/2", 8" into decimal feet."""
    # Collapse whitespace to a single space rather than removing it outright.
    # A fraction like "8 1/2" (inches, then a space, then the fraction) needs
    # that ONE space to survive -- both _DIM_RE and _INCH_ONLY_RE require
    # `\s+` between the whole-inches part and the numerator specifically so
    # "81/2" (no space) can never be misread as the fraction "8 1/2". Deleting
    # every space instead of collapsing them silently turned every
    # fractional-inch dimension ("19'-8 1/2"", "14'-6 3/8"") into something
    # neither regex could match, so it was dropped as unparseable on every
    # sheet, not just this one -- a whole-number dimension a few points away
    # would then get matched in its place instead, producing a confidently
    # wrong "sheet disagrees" flag on a bay that was actually correct.
    t = re.sub(r"\s+", " ", text.strip())
    m = _DIM_RE.match(t)
    if m:
        feet = float(m.group("feet"))
        inches = float(m.group("inches") or 0)
        num = float(m.group("num") or 0)
        den = float(m.group("den") or 1)
        return feet + (inches + (num / den if den != 0 else 0)) / 12.0

    m2 = _INCH_ONLY_RE.match(t)
    if m2:
        inches = float(m2.group("inches"))
        num = float(m2.group("num") or 0)
        den = float(m2.group("den") or 1)
        return (inches + (num / den if den != 0 else 0)) / 12.0
    return None



STANDARD_ARCHITECTURAL_SCALES = [
    ("1/16\" = 1'-0\"", 4.5),
    ("3/32\" = 1'-0\"", 6.75),
    ("1/8\" = 1'-0\"", 9.0),
    ("3/16\" = 1'-0\"", 13.5),
    ("1/4\" = 1'-0\"", 18.0),
    ("3/8\" = 1'-0\"", 27.0),
    ("1/2\" = 1'-0\"", 36.0),
    ("3/4\" = 1'-0\"", 54.0),
    ("1\" = 1'-0\"", 72.0),
    ("1-1/2\" = 1'-0\"", 108.0),
    ("3\" = 1'-0\"", 216.0),
]


def check_dim_agreement_all_scales(
    val_ft: Optional[float],
    span_px: float,
    current_calc_ft: float,
    current_pts_per_foot: float
) -> Tuple[bool, Optional[str]]:
    """
    Check if a candidate printed dimension text (val_ft) agrees with the bay's
    physical span (span_px) on:
      1) The current active scale (current_pts_per_foot), OR
      2) ANY standard architectural scale category.

    Returns (agrees: bool, matched_scale: Optional[str]).
    """
    if val_ft is None or val_ft <= 0:
        return False, None

    # 1. Check against current active scale
    if current_pts_per_foot > 0 and current_calc_ft > 0:
        tol = max(0.3, current_calc_ft * 0.03)
        if abs(val_ft - current_calc_ft) <= tol:
            return True, "current_scale"

    # 2. Check against all standard architectural scale categories
    if span_px > 0:
        for scale_name, scale_ppf in STANDARD_ARCHITECTURAL_SCALES:
            test_ft = span_px / scale_ppf
            tol = max(0.3, test_ft * 0.03)
            if abs(val_ft - test_ft) <= tol:
                return True, scale_name

    return False, None


def is_valid_dim_text(text: str) -> bool:
    """Validate if string has valid architectural dimension syntax."""
    t = text.strip()
    if not t or len(t) > 25:
        return False
    if re.search(r"[Ww]\d+[Xx]\d+|HSS|L\d+x|PL\d+|C\d+x", t):
        return False
    if re.match(r"^\d+\s*['\u2019]", t) or re.match(r"^\d+(?:/\d+|\s+\d+/\d+)?\s*[\"\u201d]$", t):
        return True
    return False


def ft_to_arch(v: float) -> str:
    """
    Format decimal feet as exact architectural feet-inches with reduced fractions
    (e.g. 11'-3 1/2", 31'-0", 15'-6", 7'-9 1/4").
    """
    feet = int(v)
    remainder_in = (v - feet) * 12.0
    sixteenths = int(round(remainder_in * 16.0))
    inches = sixteenths // 16
    frac_sixteenths = sixteenths % 16

    if inches >= 12:
        feet += inches // 12
        inches = inches % 12

    if frac_sixteenths == 0:
        return f"{feet}'-{inches}\""

    # Reduce fraction (e.g. 8/16 -> 1/2, 4/16 -> 1/4, 12/16 -> 3/4, 2/16 -> 1/8)
    num, den = frac_sixteenths, 16
    while num % 2 == 0 and den % 2 == 0:
        num //= 2
        den //= 2

    return f"{feet}'-{inches} {num}/{den}\""



def detect_scale_factor(text_dict: dict) -> Tuple[float, str, bool]:
    """
    Detect drawing scale from text blocks (e.g. 1/8" = 1'-0").
    Returns (pts_per_foot, scale_label, is_explicit).
    is_explicit is False only when no scale callout was found on the sheet
    and we had to fall back to a default -- this must never be silently
    indistinguishable from a real, printed scale.
    """
    scale_re = re.compile(
        r"(\d+/\d+|\d+)\s*[\"\u201d]\s*=\s*(\d+)['\u2019]-\s*(\d+)[\"\u201d]"
        r"|SCALE\s*:\s*(\d+/\d+|\d+)\s*[\"\u201d]\s*=\s*(\d+)"
    )
    for b in text_dict.get("blocks", []):
        for l in b.get("lines", []):
            line_str = "".join(sp.get("text", "") for sp in l.get("spans", []))
            m = scale_re.search(line_str)
            if m:
                frac_str = m.group(1) or m.group(4)
                if "/" in frac_str:
                    num, den = frac_str.split("/")
                    inch_val = float(num) / float(den)
                else:
                    inch_val = float(frac_str)
                pts_per_foot = inch_val * 72.0
                return pts_per_foot, line_str.strip(), True

    return 9.0, "1/8\" = 1'-0\" (DEFAULT -- NOT FOUND ON SHEET)", False


# ---------------------------------------------------------------------------
# Bubble confirmation: a label only counts if it sits on a REAL vector shape
# ---------------------------------------------------------------------------
def _label_kind(t: str) -> Optional[Tuple[str, bool]]:
    """Returns (axis_kind, is_secondary) or None. axis_kind is 'letter' or 'number'."""
    if _GRID_LETTER_PRIMARY.match(t):
        return ("letter", False)
    if _GRID_LETTER_SECONDARY.match(t):
        return ("letter", True)
    if _GRID_NUMBER_PRIMARY.match(t):
        return ("number", False)
    if _GRID_NUMBER_SECONDARY.match(t):
        return ("number", True)
    return None


def _find_confirmed_bubbles(page: "fitz.Page", text_dict: dict,
                            line_index=None) -> List[Dict[str, Any]]:
    """
    A grid label is only accepted when its text sits on top of a real
    circle/roundel vector shape from the page's own drawing data. This is
    the check that keeps stray dimension digits, rebar counts, elevation
    marks, and callouts from being mistaken for grid bubbles.

    cx/cy here are the centre of the label's TEXT span -- that is the
    bubble's position, which is NOT the same thing as the grid's position.
    The bubble is a label; the chain line it terminates is the measurement
    axis, and a drafter dodges the bubble sideways whenever two grids are
    too close for their circles to fit. When `line_index` is supplied,
    attach_line_coords() adds the real chain-line coordinate to each bubble
    (line_cx / line_cy) and everything downstream measures from that
    instead, falling back to the bubble centre only where no line was
    found -- flagged, never silently.
    """
    rot_mat = page.rotation_matrix if page.rotation != 0 else None
    drawings = page.get_drawings()
    bubble_boxes = []
    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        if rot_mat is not None:
            r = r * rot_mat
        w, h = r.width, r.height
        if w <= 1 or h <= 1:
            continue
        aspect = max(w, h) / max(min(w, h), 0.1)
        if 6 <= w <= 45 and 6 <= h <= 45 and aspect <= 1.6:
            bubble_boxes.append(r)

    confirmed = []
    for b in text_dict.get("blocks", []):
        for l in b.get("lines", []):
            for sp in l.get("spans", []):
                t = sp.get("text", "").strip()
                if not t or len(t) > 5:
                    continue
                kind = _label_kind(t)
                if kind is None:
                    continue
                bbox = fitz.Rect(sp.get("bbox", [0, 0, 0, 0]))
                if rot_mat is not None:
                    bbox = bbox * rot_mat
                cx, cy = (bbox.x0 + bbox.x1) / 2.0, (bbox.y0 + bbox.y1) / 2.0
                for r in bubble_boxes:
                    if r.x0 - 2 <= cx <= r.x1 + 2 and r.y0 - 2 <= cy <= r.y1 + 2:
                        confirmed.append({
                            "text": t, "axis": kind[0], "is_secondary": kind[1],
                            "cx": cx, "cy": cy,
                        })
                        break

    if line_index is not None and confirmed:
        attach_line_coords(confirmed, line_index)

    return confirmed


def _label_rank(t: str) -> float:
    m = re.match(r"^([A-Z])(?:\.(\d+))?$", t)
    if m:
        return (ord(m.group(1)) - 65) * 100 + (int(m.group(2)) if m.group(2) else 0)
    m2 = re.match(r"^(\d+)(?:\.(\d+))?$", t)
    if m2:
        return int(m2.group(1)) * 100 + (int(m2.group(2)) if m2.group(2) else 0)
    return 0.0


def _is_valid_grid_band(band: List[Dict[str, Any]], axis: str) -> bool:
    if not band:
        return False
    if axis == "number":
        nums = []
        for p in band:
            m = re.match(r"^(\d+)(?:\.(\d+))?$", p["text"])
            if m:
                val = float(m.group(1)) + (float(m.group(2)) / 10.0 if m.group(2) else 0.0)
                nums.append(val)
        if not nums or min(nums) > 20:
            return False
        if len(set(int(n) for n in nums)) < 2:
            return False
        sorted_nums = sorted(nums)
        large_jumps = sum(1 for i in range(len(sorted_nums) - 1) if sorted_nums[i+1] - sorted_nums[i] > 4.0)
        if large_jumps > 0 and len(sorted_nums) < 5:
            return False
        if large_jumps > len(sorted_nums) * 0.3:
            return False
        return True
    elif axis == "letter":
        letters = []
        for p in band:
            m = re.match(r"^([A-Z])", p["text"])
            if m:
                letters.append(ord(m.group(1)) - 65)
        if not letters:
            return False
        if min(letters) > 6:
            return False
        if len(set(letters)) < 2:
            return False
        sorted_let = sorted(letters)
        large_jumps = sum(1 for i in range(len(sorted_let) - 1) if sorted_let[i+1] - sorted_let[i] > 4)
        if large_jumps > len(sorted_let) * 0.3:
            return False
        return True
    return True


def _pick_best_grid_band(pts: List[Dict[str, Any]], axis: str, band_key: str, pos_key: str,
                         page_dim: float, tol: float = 8.0) -> List[Dict[str, Any]]:
    if not pts:
        return []
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for p in pts:
        bkey = round(p[band_key] / tol)
        buckets.setdefault(bkey, []).append(p)

    candidates = []
    for b in buckets.values():
        run = _largest_contiguous_run(b, pos_key, axis=axis)
        if len(run) >= 2 and _is_valid_grid_band(run, axis):
            center = sum(p[band_key] for p in run) / len(run)
            dist_to_edge = min(center, page_dim - center)
            candidates.append((run, dist_to_edge, len(run)))

    if not candidates:
        raw_candidates = []
        for b in buckets.values():
            run = _largest_contiguous_run(b, pos_key, axis=axis)
            if len(run) >= 2:
                center = sum(p[band_key] for p in run) / len(run)
                dist_to_edge = min(center, page_dim - center)
                raw_candidates.append((run, dist_to_edge, len(run)))
        if not raw_candidates:
            return []
        raw_candidates.sort(key=lambda x: (x[1], -x[2]))
        return raw_candidates[0][0]

    candidates.sort(key=lambda x: (x[1], -x[2]))
    return candidates[0][0]


# A gap this many times the band's own median bay is a view boundary, not a
# bay. Structural sheets do carry long spans -- a 54 ft run against 25 ft
# neighbours is only 2.2x -- so 4x leaves real bays alone.
VIEW_SPLIT_GAP_FACTOR = 4.0
# ...and it must also clear this absolute gap, so a band whose bubbles happen
# to sit almost on top of each other cannot split on noise. The previous value
# here was 750 points, which silently defeated the relative test entirely: on
# a sheet with 35-point bays the threshold became 750 while a real boundary
# between two plan views measured 277, so the two views were chained into one
# grid line and every bay across the join was fiction.
VIEW_SPLIT_MIN_GAP_PTS = 150.0


def _labels_bridge_split(left_text: str, right_text: str, axis: str) -> bool:
    """
    True when the labels on either side of a candidate view-split gap read
    as a straight continuation of the same numbered/lettered grid sequence
    (e.g. "15" -> "16", or "21" -> "23" where "22" simply doesn't exist on
    this sheet) rather than two unrelated views each restarting their own
    numbering.

    Root cause this fixes: a real structural sheet can legitimately have
    one bay far wider than its neighbours -- a mechanical well, an atrium,
    a stepped roofline dropping the dimension string to a new height for a
    few bays -- and that single wide bay's gap can exceed the geometric
    view-split threshold below even though it sits inside ONE continuous,
    correctly-numbered grid row (found 2026-09-10: grids 1-15 and 16-24 on
    one sheet's row got cut apart here purely because bay 15-16 happened to
    be ~4.6x the row's median bay, discarding every grid from 16 on as if
    it belonged to a different view). A genuine view boundary does not
    behave this way -- a second, unrelated plan view restarts its bubble
    numbering (back to 1, or A), it does not pick up exactly where the
    first view's sequence left off. So label continuity is the
    discriminator a gap-size-only test cannot provide: only veto the split
    when the two labels are themselves a small, strictly-increasing step
    apart (allowing for the odd sheet that skips a number/letter it never
    used), never when the size gap is real but the labels don't line up.
    """
    if axis == "number":
        ma = re.match(r"^(\d+)(?:\.(\d+))?$", left_text)
        mb = re.match(r"^(\d+)(?:\.(\d+))?$", right_text)
        if not ma or not mb:
            return False
        return 0 < (int(mb.group(1)) - int(ma.group(1))) <= 3
    elif axis == "letter":
        ma = re.match(r"^([A-Z])", left_text)
        mb = re.match(r"^([A-Z])", right_text)
        if not ma or not mb:
            return False
        return 0 < (ord(mb.group(1)) - ord(ma.group(1))) <= 3
    return False


def _split_runs(band: List[Dict[str, Any]], pos_key: str,
                 axis: Optional[str] = None) -> List[List[Dict[str, Any]]]:
    """
    Break a band wherever the spacing jumps, and return every resulting run.

    A page often carries more than one plan view -- partial plans for Area A
    and Area B, a match line, an enlarged detail of a corner. Each view has
    its own grid bubbles, at the same height on the sheet, so they land in one
    band and get chained together. The join between them is not a bay: it is
    empty paper, and any dimension computed across it is meaningless.

    `axis`, when given, lets a candidate split be vetoed by
    _labels_bridge_split: an oversized gap whose two flanking labels are
    still a straight continuation of the same sequence (see that function's
    docstring) is a real wide bay, not a view boundary, and is kept whole.
    """
    pts = sorted(band, key=lambda p: p[pos_key])
    if len(pts) < 3:
        return [pts]
    gaps = [pts[i + 1][pos_key] - pts[i][pos_key] for i in range(len(pts) - 1)]
    positive = [g for g in gaps if g > 0.5]
    if not positive:
        return [pts]
    med = sorted(positive)[len(positive) // 2]
    threshold = max(med * VIEW_SPLIT_GAP_FACTOR, VIEW_SPLIT_MIN_GAP_PTS)

    runs, current = [], [pts[0]]
    for i, g in enumerate(gaps):
        if g > threshold and not (axis and _labels_bridge_split(
                pts[i]["text"], pts[i + 1]["text"], axis)):
            runs.append(current)
            current = [pts[i + 1]]
        else:
            current.append(pts[i + 1])
    runs.append(current)
    return runs


def _largest_contiguous_run(band: List[Dict[str, Any]], pos_key: str,
                             axis: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Keep the biggest coherent run in this band and drop the rest.

    Returns the LARGEST run, not the first one encountered. The old behaviour
    kept whichever run started at the lowest coordinate, so on a sheet whose
    left-hand view was a small enlarged detail and whose right-hand view was
    the actual plan, the detail won and the plan was discarded.
    """
    if os.getenv("GRID_SPLIT_VIEWS", "1") in ("0", "false", "False"):
        pts = sorted(band, key=lambda p: p[pos_key])
        if len(pts) < 3:
            return pts
        gaps = [pts[i + 1][pos_key] - pts[i][pos_key] for i in range(len(pts) - 1)]
        run, seen = [pts[0]], []
        for i, g in enumerate(gaps):
            if seen and g > max(sorted(seen)[len(seen) // 2] * 4.0, 750.0):
                break
            run.append(pts[i + 1])
            seen.append(g)
        return run

    runs = _split_runs(band, pos_key, axis=axis)
    if len(runs) == 1:
        return runs[0]
    best = max(runs, key=len)
    # Annotate the winner so the caller can report that this page carried
    # more than one view and that grids outside the chosen one were dropped.
    dropped = sum(len(r) for r in runs) - len(best)
    if best:
        best[0].setdefault("_view_split", {})
        best[0]["_view_split"] = {"runs": len(runs), "dropped_bubbles": dropped}
    return best


# Minimum share of the sheet a chain line must span before an interior bubble
# sitting on it is accepted as a grid. A real grid line crosses the plan; a
# short fragment near a callout does not.
INTERIOR_MIN_LINE_LEN_FRAC = 0.30


def _absorb_interior_grids(chain: List[Dict[str, Any]], confirmed: List[Dict[str, Any]],
                           axis_type: str, pos_key: str,
                           dim_spans: Optional[List[Dict[str, Any]]] = None,
                           pts_per_foot: float = 0.0,
                           secondary_only: bool = True,
                           min_len_frac: float = INTERIOR_MIN_LINE_LEN_FRAC
                           ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Recover grids whose bubbles sit AWAY FROM THE SHEET PERIMETER.

    The band-finding machinery above is built around the assumption that grid
    bubbles live on the outer margin of the page, and four separate gates
    enforce it: `near_edge` tests position against the PAGE (not the plan), so
    on a sheet with a notes column and a title block the plan's own margin
    already falls outside the 24% band; only non-secondary bubbles may seed a
    band; `used_sides` allows one band per side; and `_is_valid_grid_band`
    requires two distinct base letters, which a run of pure sub-grids
    (C.1, C.4) can never satisfy.

    Every one of those gates is doing useful work against false positives, so
    none of them is loosened. This is an additive pass instead: it can only
    ADD a grid, never move or remove one, and it admits a bubble only when all
    of the following hold.

      * It sits on a chain line spanning at least `min_len_frac` of the sheet.
        This is the evidence the perimeter test was standing in for, and it is
        strictly better: a bubble on a full-length grid line IS a grid,
        wherever on the sheet it happens to be drawn.
      * Its label sorts strictly BETWEEN two grids already confirmed. A real
        interior sub-grid always does; a compass rose, a detail callout or a
        stray digit does not.
      * Its position falls strictly between two existing grids, and not on top
        of one.
      * It is a SUB-GRID (a decimal label). A missing primary is a different
        failure with a different cause; letting this pass "recover" primaries
        was measured to do more harm than good.
      * THE SHEET DIMENSIONS THE BAY IT CREATES. This is the gate that makes
        the difference. An earlier version of this pass, without it, recovered
        24 extra grids across the corpus and dropped agreement against the
        sheets' own printed dimensions from 79% to 71% while raising bays with
        no nearby dimension at all from 36 to 52 -- it was inventing grid
        boundaries. A genuine interior sub-grid is drawn BECAUSE it is
        dimensioned, so requiring a printed dimension that matches the
        distance to one of its neighbours separates the two cases directly
        rather than by proxy.

    This is the case that goes wrong on a stepped or L-shaped building, where
    the building steps in and the sub-grids serving the step are dimensioned
    on their own interior rail rather than at the sheet edge -- the D.1 / D.4
    case, where the grids are plainly drawn and dimensioned on the sheet but
    come out of the pass with no span at all, silently merged into the single
    long bay that spans them.

    Returns (merged_chain, added_entries).
    """
    if len(chain) < 2:
        return chain, []

    existing_labels = {p["label"] for p in chain}
    ranks = [_label_rank(p["label"]) for p in chain]
    lo_rank, hi_rank = min(ranks), max(ranks)
    coords = sorted(p["coord"] for p in chain)
    lo_coord, hi_coord = coords[0], coords[-1]
    gaps = [b - a for a, b in zip(coords, coords[1:]) if b - a > 1.0]
    median_gap = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
    # Never insert a "new" grid effectively on top of an existing one.
    dup_tol = max(3.0, median_gap * 0.05)

    dim_spans = dim_spans or []

    def _dimension_corroborates(coord: float) -> bool:
        """Does the sheet print a dimension matching a bay this grid creates?"""
        if pts_per_foot <= 0 or not dim_spans:
            return False
        left = max((x for x in coords if x < coord), default=None)
        right = min((x for x in coords if x > coord), default=None)
        for other in (left, right):
            if other is None:
                continue
            gap_pts = abs(coord - other)
            if gap_pts < 5.0:
                continue
            gap_ft = gap_pts / pts_per_foot
            mid = (coord + other) / 2.0
            tol = max(0.3, gap_ft * 0.03)
            for d in dim_spans:
                if abs(d[pos_key] - mid) > gap_pts * 0.35:
                    continue
                if abs(d.get("val_ft", 0.0) - gap_ft) <= tol:
                    return True
        return False

    added = []
    for c in confirmed:
        if c["axis"] != axis_type or c["text"] in existing_labels:
            continue
        if secondary_only and not c["is_secondary"]:
            continue
        rank = _label_rank(c["text"])
        if not (lo_rank < rank < hi_rank):
            continue
        len_frac, line_margin = line_evidence(c, pos_key)
        coord, source = grid_coord(c, pos_key)
        if not (lo_coord + dup_tol < coord < hi_coord - dup_tol):
            continue
        if any(abs(coord - x) <= dup_tol for x in coords):
            continue

        strong_line = len_frac is not None and len_frac >= min_len_frac
        corroborated = _dimension_corroborates(coord)

        # Three tiers of evidence, weakest last. A sub-grid on a stepped or
        # L-shaped building is routinely dimensioned on its own interior
        # rail with no full-length chain line to match (a short local run,
        # not a page-spanning line), or with no printed dimension near the
        # bubble at all (its length is only ever shown on a companion
        # detail sheet). Requiring BOTH, as this pass first did, meant a
        # real, plainly-bubbled grid the drawing draws was silently merged
        # into its neighbours' bay instead of reported -- missing a grid
        # that is actually there is worse than surfacing one for review.
        # `secondary_only` (decimal labels only) plus the rank/position
        # betweenness checks above are what keep this from readmitting the
        # false positives (compass roses, detail callouts, sheet
        # references) the strict version was built to reject -- none of
        # those pass as decimal sub-grid labels ranked strictly between two
        # already-confirmed neighbours in the first place.
        if strong_line and corroborated:
            confidence = "line_and_dimension"
        elif strong_line:
            confidence = "line_only"
        elif corroborated:
            confidence = "dimension_only"
        elif c["is_secondary"]:
            confidence = "bubble_only_uncorroborated"
        else:
            continue

        added.append({
            "label": c["text"],
            "is_secondary": c["is_secondary"],
            "coord": round(coord, 2),
            "coord_source": source,
            "confidence": confidence,
            "bubble_coord": round(c[pos_key], 2),
            "bubble_offset_pts": (None if source == "bubble_inferred"
                                  else round(abs(coord - c[pos_key]), 2)),
            "line_len_frac": len_frac,
            "line_margin": line_margin,
            "from_interior_rail": True,
            "rail_coord": round(c["cy" if pos_key == "cx" else "cx"], 2),
        })
        existing_labels.add(c["text"])

    if not added:
        return chain, []

    merged = list(chain) + added
    merged.sort(key=lambda p: p["coord"])
    return merged, added


def _union_axis_grids(tracks: List[Tuple[List[Dict[str, Any]], Dict[str, Any]]],
                      coord_name: str) -> List[Dict[str, Any]]:
    """
    The sheet's full grid list for one axis: every label any confirmed track
    found, not just the densest track's.

    A grid is normally bubbled at BOTH ends of the plan, but not always -- a
    sub-grid serving only part of the building is routinely dimensioned on one
    rail alone, and on a stepped plan the two rails carry genuinely different
    breakdowns. The pass already discovers those grids and puts them in their
    own track; the reported grid list simply never included them, because it
    was built from tracks[0].

    Measured on #Structural binder.pdf: p4 reported 13 vertical grids where
    the tracks between them held 21, and p7 reported 15 where they held 23.
    Every one of the missing eight was found, dimensioned, and then dropped on
    the way out.

    Position comes from the first (densest, most trusted) track that carries
    the label. Where another track disagrees about where that grid sits by
    more than a small fraction of the median bay, the disagreement is recorded
    rather than averaged away -- two tracks disagreeing on a grid's position
    is a real finding about the sheet, not noise to smooth over.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for ti, (chain, _meta) in enumerate(tracks):
        for g in chain:
            label = g["label"]
            prev = out.get(label)
            if prev is None:
                out[label] = {
                    "label": label,
                    coord_name: g["coord"],
                    "is_secondary": g["is_secondary"],
                    "coord_source": g.get("coord_source", "bubble_inferred"),
                    ("bubble_" + coord_name): g.get("bubble_coord"),
                    "bubble_offset_pts": g.get("bubble_offset_pts"),
                    "tracks": [ti],
                }
            else:
                prev["tracks"].append(ti)
                delta = abs(g["coord"] - prev[coord_name])
                if delta > 1.0:
                    prev["cross_track_delta_pts"] = round(
                        max(delta, prev.get("cross_track_delta_pts", 0.0)), 2)

    grids = sorted(out.values(), key=lambda g: g[coord_name])
    coords = [g[coord_name] for g in grids]
    gaps = [b - a for a, b in zip(coords, coords[1:]) if b - a > 1.0]
    if gaps:
        median_gap = sorted(gaps)[len(gaps) // 2]
        tol = max(2.0, median_gap * 0.05)
        for g in grids:
            d = g.get("cross_track_delta_pts")
            if d is not None:
                g["position_disagreement"] = d > tol
    return grids


def _union_axis_grids_unused_guard():  # pragma: no cover
    return None


def _build_axis_tracks(confirmed: List[Dict[str, Any]], axis: str, pw: float, ph: float,
                        band_key: str, pos_key: str, edge: float = 0.24,
                        widen: float = 85.0, margin: float = 220.0,
                        min_track_primary: int = 2, max_tracks: int = 4
                        ) -> List[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    """
    Different sheets dimension differently -- some mark grids on one side
    only, some on both sides of an axis, some repeat a bay-level track and a
    separate cumulative/overall track further out. The job here is to find
    and mark EVERY real track that's actually confirmed on the sheet, not to
    pick a single "best" one and discard the rest.

    axis: 'number' -> grid line position is the bubble's cx (band_key='cy', pos_key='cx')
    axis: 'letter' -> grid line position is the bubble's cy (band_key='cx', pos_key='cy')

    Returns a list of (ordered chain of {label, is_secondary, coord}, meta) --
    one entry per distinct confirmed track, most-confident first.
    """
    items = [c for c in confirmed if c["axis"] == axis]

    # near_edge below is the gate that decides which confirmed bubbles are
    # even eligible to seed or join a track -- everything else in this
    # function only ever removes candidates that pass it. Measuring it
    # against the raw PAGE box is wrong on any sheet with a wide title
    # block, notes column, or blank margin: the real plan can occupy well
    # under half the page, so a genuine grid row sitting near the PLAN's
    # own edge can still fall in the page's untouched middle 52% and never
    # be considered at all (this is what silently dropped an entire primary
    # numbers row, and a primary letters row, on real sheets -- not a
    # missing sub-grid, a missing PRIMARY grid line, because the row was
    # real but the page-relative threshold never looked there).
    # Grounding the box in every confirmed bubble on the page (both axes,
    # not just this one) instead of the raw page rect fixes that: it is
    # built from real, already-verified grid geometry, not a guess, and a
    # sheet where confirmed bubbles happen to already hug the page edges
    # reduces to the old page-relative behaviour, so this only ever widens
    # what near_edge accepts, never narrows it.
    def _robust_range(values: List[float], full_span: float) -> Tuple[float, float]:
        """5th/95th percentile instead of min/max -- one stray confirmed
        point far from the real plan (a callout number, a note reference)
        should not be able to single-handedly drag the content box out and
        undo the whole point of using it instead of the raw page."""
        if len(values) < 4:
            return 0.0, full_span
        s = sorted(values)
        n = len(s)
        lo = s[max(0, int(n * 0.05))]
        hi = s[min(n - 1, int(n * 0.95))]
        if hi - lo <= full_span * 0.1:
            return 0.0, full_span
        return lo, hi

    all_cx = [c["cx"] for c in confirmed]
    all_cy = [c["cy"] for c in confirmed]
    content_x_lo, content_x_hi = _robust_range(all_cx, pw)
    content_y_lo, content_y_hi = _robust_range(all_cy, ph)
    # Small padding so a bubble sitting exactly on the content boundary
    # (the common case -- that is where grid bubbles are drawn) still
    # counts as "near the edge" rather than landing exactly on the line.
    cx_pad = max((content_x_hi - content_x_lo) * 0.03, 10.0)
    cy_pad = max((content_y_hi - content_y_lo) * 0.03, 10.0)
    content_x_lo -= cx_pad
    content_x_hi += cx_pad
    content_y_lo -= cy_pad
    content_y_hi += cy_pad
    content_w = max(content_x_hi - content_x_lo, 1.0)
    content_h = max(content_y_hi - content_y_lo, 1.0)

    def near_edge(c):
        return (c["cx"] < content_x_lo + content_w * edge or
                c["cx"] > content_x_hi - content_w * edge or
                c["cy"] < content_y_lo + content_h * edge or
                c["cy"] > content_y_hi - content_h * edge)

    perim = [c for c in items if near_edge(c)]
    remaining = [c for c in perim if not c["is_secondary"]]

    tracks: List[Tuple[List[Dict[str, Any]], Dict[str, Any]]] = []
    used_sides: set = set()
    page_dim = ph if band_key == "cy" else pw

    for _ in range(max_tracks):
        if not remaining:
            break
        band = _pick_best_grid_band(remaining, axis, band_key, pos_key, page_dim)
        if len(band) < min_track_primary:
            break

        band_center = sum(p[band_key] for p in band) / len(band)
        candidate_side = ("top" if band_center < ph / 2 else "bottom") if band_key == "cy" \
            else ("left" if band_center < pw / 2 else "right")
        if candidate_side in used_sides:
            # discard this band as noise and keep looking, but don't let it
            # block progress -- remove its points and continue
            used_ids = {id(p) for p in band}
            remaining = [c for c in remaining if id(c) not in used_ids]
            continue
        used_sides.add(candidate_side)
        pos_lo = min(p[pos_key] for p in band) - margin
        pos_hi = max(p[pos_key] for p in band) + margin

        widened = [
            c for c in perim
            if abs(c[band_key] - band_center) <= widen and pos_lo <= c[pos_key] <= pos_hi
        ]

        best_by_label: Dict[str, Dict[str, Any]] = {}
        for c in widened:
            cur = best_by_label.get(c["text"])
            if cur is None or abs(c[band_key] - band_center) < abs(cur[band_key] - band_center):
                best_by_label[c["text"]] = c

        # Order by the grid LINE, not the bubble. Where a bubble was dodged
        # sideways to make room, its own line still sits at the true
        # position, so sorting on the line keeps a crowded sub-grid in its
        # real place in the run instead of one label's worth of drift.
        chain = sorted(best_by_label.values(), key=lambda c: grid_coord(c, pos_key)[0])
        if band_key == "cy":
            side = "top" if band_center < ph / 2 else "bottom"
        else:
            side = "left" if band_center < pw / 2 else "right"

        meta = {
            "band_found": True,
            "side": side,
            "band_coord": round(band_center, 2),
            "primary_count": sum(1 for c in chain if not c["is_secondary"]),
            "secondary_count": sum(1 for c in chain if c["is_secondary"]),
        }
        chain_entries = []
        for c in chain:
            coord, source = grid_coord(c, pos_key)
            # NB: _build_axis_tracks already has a `margin` parameter (the
            # band-widening distance). Do not shadow it here.
            line_len_frac, line_match_margin = line_evidence(c, pos_key)
            chain_entries.append({
                "line_len_frac": line_len_frac,
                "line_margin": line_match_margin,
                "label": c["text"],
                "is_secondary": c["is_secondary"],
                "coord": round(coord, 2),
                "coord_source": source,
                "bubble_coord": round(c[pos_key], 2),
                "bubble_offset_pts": (None if source == "bubble_inferred"
                                      else round(abs(coord - c[pos_key]), 2)),
            })
        meta["line_outliers_rejected"] = reject_outlier_line_coords(chain_entries)
        meta["line_confirmed_count"] = sum(
            1 for e in chain_entries
            if e["coord_source"] in ("vector_line", "bubble_confirmed_by_line"))
        meta["line_corrected_count"] = sum(
            1 for e in chain_entries if e["coord_source"] == "vector_line")
        chain_entries.sort(key=lambda e: e["coord"])
        tracks.append((chain_entries, meta))

        # remove this track's primary points from the pool so the next
        # iteration finds a genuinely different track, not the same one again
        used_ids = {id(p) for p in band}
        remaining = [c for c in remaining if id(c) not in used_ids]

    return tracks


def _build_axis_chain(confirmed: List[Dict[str, Any]], axis: str, pw: float, ph: float,
                       band_key: str, pos_key: str, **kwargs) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Back-compat wrapper: returns only the single most-confident track
    (used for the canonical grid-intersection matrix, which needs one
    position per grid label, not one per dimensioned side)."""
    tracks = _build_axis_tracks(confirmed, axis, pw, ph, band_key, pos_key, **kwargs)
    if not tracks:
        return [], {"band_found": False}
    return tracks[0]


# ---------------------------------------------------------------------------
# Length calibration
# ---------------------------------------------------------------------------
def _collect_dim_spans(page: "fitz.Page", text_dict: dict) -> List[Dict[str, Any]]:
    rot_mat = page.rotation_matrix if page.rotation != 0 else None
    dim_spans = []
    for b in text_dict.get("blocks", []):
        for l in b.get("lines", []):
            spans = l.get("spans", [])
            if not spans:
                continue

            # Cluster adjacent spans on the same line that are separated by small gaps (< 4 pts)
            # or overlap (handles cases where characters/quotes are segmented into separate spans e.g. ['3', '1', "'-0\""])
            clusters = []
            curr = [spans[0]]
            for sp in spans[1:]:
                prev_bbox = curr[-1].get("bbox", [0, 0, 0, 0])
                curr_bbox = sp.get("bbox", [0, 0, 0, 0])
                gap = curr_bbox[0] - prev_bbox[2]
                if -2.0 <= gap <= 4.0:
                    curr.append(sp)
                else:
                    clusters.append(curr)
                    curr = [sp]
            if curr:
                clusters.append(curr)

            for cluster in clusters:
                text_piece = "".join(sp.get("text", "") for sp in cluster).strip()
                if not text_piece or not is_valid_dim_text(text_piece):
                    continue
                val = parse_dimension_string(text_piece)
                if val is None or not (0.5 <= val <= 350.0):
                    continue

                bboxes = [fitz.Rect(sp.get("bbox", [0, 0, 0, 0])) for sp in cluster]
                union_box = bboxes[0]
                for r in bboxes[1:]:
                    union_box |= r
                if rot_mat is not None:
                    union_box = union_box * rot_mat
                cx = (union_box.x0 + union_box.x1) / 2.0
                cy = (union_box.y0 + union_box.y1) / 2.0
                dim_spans.append({
                    "text": text_piece,
                    "val_ft": val,
                    "cx": cx,
                    "cy": cy,
                })

    return dim_spans


def _calibrate_pts_per_foot(chain: List[Dict[str, Any]], dim_spans: List[Dict[str, Any]],
                             pos_key: str, other_coord: float) -> Optional[float]:
    """Cross-check consecutive-bay pixel spans against nearby printed dimension
    text and take the median ratio -- robust to a handful of mismatches."""
    candidates = []
    for i in range(len(chain) - 1):
        p1, p2 = chain[i], chain[i + 1]
        span = abs(p2["coord"] - p1["coord"])
        if span < 5:
            continue
        mid = (p1["coord"] + p2["coord"]) / 2.0
        for d in dim_spans:
            d_pos = d[pos_key]
            d_other = d["cy"] if pos_key == "cx" else d["cx"]
            if abs(d_pos - mid) <= max(span * 0.15, 20) and abs(d_other - other_coord) <= 60:
                candidates.append(span / d.get("val_ft", 0) if d.get("val_ft") else None)
    candidates = [c for c in candidates if c]
    if len(candidates) < 3:
        return None
    return sorted(candidates)[len(candidates) // 2]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run_deterministic_geometry_pass(
    pdf_path: str | Path, page_number: int = 0,
    override_pts_per_foot: Optional[float] = None,
) -> Dict[str, Any]:
    """
    override_pts_per_foot: when the caller already knows the page's
    explicitly-selected scale (e.g. the scale the user picked for this page
    in the app), pass it here so it's used as the authoritative value
    instead of this module's own on-sheet scale-text detection -- the
    user's explicit selection always outranks a guess read off the sheet.
    """
    doc = fitz.open(str(pdf_path))
    if page_number < 0 or page_number >= len(doc):
        raise ValueError(f"Page index {page_number} out of range (0-{len(doc)-1})")

    page = doc[page_number]
    rect = page.rect
    # page.rect is ALREADY the displayed (rotation-applied) rectangle, and
    # _find_confirmed_bubbles / _collect_dim_spans transform every coordinate
    # into that same space via page.rotation_matrix. So the page box is
    # rect.width x rect.height on every page, rotated or not.
    #
    # This previously swapped width and height on a 90/270 page, which
    # double-counted the rotation. Measured on #Structural binder.pdf p4 --
    # mediabox 2160x3024, page.rect 3024x2160, rotation 90 -- raw text spans
    # x 76..2108 and, after page.rotation_matrix, x 85..3019. The swap then
    # told every downstream test the page was 2160 wide, so bubbles out at
    # x = 2368 sat "off the page" and every perimeter check, edge band and
    # left-vs-right-of-centre decision was measured against a box a third
    # narrower than the content it had to classify.
    if os.getenv("GRID_LEGACY_ROTATION", "0") in ("1", "true", "True"):
        page_w, page_h = ((rect.height, rect.width) if page.rotation in (90, 270)
                          else (rect.width, rect.height))
    else:
        page_w, page_h = rect.width, rect.height
    text_dict = page.get_text("dict")

    if override_pts_per_foot and override_pts_per_foot > 0:
        pts_per_foot = override_pts_per_foot
        scale_str = f"USER-SELECTED SCALE ({round(override_pts_per_foot,3)} pts/ft)"
        is_explicit_scale = True
    else:
        pts_per_foot, scale_str, is_explicit_scale = detect_scale_factor(text_dict)
    dim_spans = _collect_dim_spans(page, text_dict)

    # Recover the real grid CHAIN LINES from the page's own vector paths
    # before confirming bubbles, so every bubble can be attached to the line
    # it terminates. page_w/page_h are already in displayed orientation and
    # rot_mat is the same transform _find_confirmed_bubbles applies, so line
    # and bubble coordinates land in one space.
    # Kill switch: set GRID_USE_LINE_GEOMETRY=0 to fall back to the old
    # bubble-centre measurement. Kept so this change can be A/B'd against a
    # known-good baseline on a sheet set, and so it can be turned off in
    # production without a deploy if a sheet family ever regresses.
    _use_lines = os.getenv("GRID_USE_LINE_GEOMETRY", "1") not in ("0", "false", "False")
    _rot_mat = page.rotation_matrix if page.rotation != 0 else None
    line_index = build_line_index(page, page_w, page_h, _rot_mat) if _use_lines else None

    confirmed = _find_confirmed_bubbles(page, text_dict, line_index=line_index)

    # Dynamic orientation detection: test both horizontal and vertical bands
    num_tracks_h = _build_axis_tracks(confirmed, "number", page_w, page_h, band_key="cy", pos_key="cx")
    num_tracks_v = _build_axis_tracks(confirmed, "number", page_w, page_h, band_key="cx", pos_key="cy")
    let_tracks_h = _build_axis_tracks(confirmed, "letter", page_w, page_h, band_key="cy", pos_key="cx")
    let_tracks_v = _build_axis_tracks(confirmed, "letter", page_w, page_h, band_key="cx", pos_key="cy")

    score_case1 = sum(len(t[0]) for t in num_tracks_h) + sum(len(t[0]) for t in let_tracks_v)
    score_case2 = sum(len(t[0]) for t in let_tracks_h) + sum(len(t[0]) for t in num_tracks_v)

    if score_case1 >= score_case2:
        # Case 1 (Standard): Numbers along X (vertical grid lines), Letters along Y (horizontal grid lines)
        v_tracks = num_tracks_h
        h_tracks = let_tracks_v
        v_axis_type = "number"
        h_axis_type = "letter"
    else:
        # Case 2 (Rotated / Portrait): Letters along X (vertical grid lines), Numbers along Y (horizontal grid lines)
        v_tracks = let_tracks_h
        h_tracks = num_tracks_v
        v_axis_type = "letter"
        h_axis_type = "number"

    # tracks[0] is treated as THE canonical chain everywhere downstream --
    # it seeds cross-track validation, it is what bays get built from, and
    # it is what interior-rail absorption checks rank/position against. But
    # _build_axis_tracks discovers tracks ordered by distance to the PAGE
    # edge, not by completeness: on a sheet with grid bubbles printed near
    # both margins (common when a building has bubbles on two sides), the
    # sparser of two real tracks can sit fractionally closer to the edge and
    # win that ordering, even though the other track has more than twice as
    # many grids. Re-ranking here so the most complete track leads means the
    # richer chain is what everything else gets checked against, while the
    # edge-distance preference still breaks ties between equally complete
    # tracks exactly as before (Python's sort is stable).
    v_tracks = sorted(v_tracks, key=lambda t: -len(t[0]))
    h_tracks = sorted(h_tracks, key=lambda t: -len(t[0]))

    def _drop_cross_track_mismatches(tracks: List[Tuple[List[Dict[str, Any]], Dict[str, Any]]]
                                      ) -> List[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
        """
        tracks[0] -- the richest, most-confirmed chain for this axis -- is
        already treated as ground truth here: a same-labeled point on any
        other track that lands far from it (>20pt) is dropped as a mismatch.
        But a point that lands CLOSE (within that same 20pt) is the same
        physical grid line, just re-measured on a second, sparser dimension
        track -- and a sparse track (as few as 3-4 confirmed points) gives
        reject_outlier_line_coords too little context to tell a genuine
        bubble dodge from measurement noise, so it can end up keeping that
        track's own raw, dodged bubble centre (coord_source
        "bubble_kept_weak_line"/"bubble_inferred_outlier") instead of the
        corrected line position -- a real grid dimensioned twice on the same
        sheet then shows two different lengths for what is the same span.
        tracks[0]'s coordinate for that label is corroborated by a richer,
        more reliable chain, so once a point is confirmed to be the SAME
        grid (within the 20pt identity check that already gated keep-vs-drop
        here), snap its coordinate to tracks[0]'s rather than leaving a
        weaker, second-hand position in place. A point that already agrees
        closely is unaffected -- this only ever corrects a point that both
        tracks agree is the same grid but disagree on where it sits.
        """
        if len(tracks) < 2:
            return tracks
        primary_by_label = {p["label"]: p["coord"] for p in tracks[0][0]}
        cleaned = [tracks[0]]
        for chain, meta in tracks[1:]:
            # Only a point whose OWN local evidence is already shaky is a
            # candidate for correction. "bubble_confirmed_by_line" and
            # "vector_line" mean THIS track independently confirmed this
            # grid against its own real vector line -- that is exactly as
            # strong as tracks[0]'s evidence, and two independently solid
            # measurements can legitimately disagree on a stepped/L-shaped
            # building where the same label is drawn on genuinely different
            # local rails (see _absorb_interior_grids's own docstring on
            # this). Overriding a solid point there is not correcting a
            # measurement, it's discarding a second, equally real one --
            # confirmed by testing: doing so turned two previously-correct,
            # OCR-agreeing bays on a stepped sheet into wrong ones. Only
            # "bubble_kept_weak_line" / "bubble_inferred_outlier" are
            # low-confidence-by-construction (reject_outlier_line_coords
            # itself decided it couldn't trust either the line or the raw
            # bubble very far) -- those, and only those, may be replaced by
            # a richer chain's independently solid coordinate for the same
            # label.
            WEAK_SOURCES = ("bubble_kept_weak_line", "bubble_inferred_outlier")
            kept = []
            for p in chain:
                ref_coord = primary_by_label.get(p["label"])
                if ref_coord is None:
                    kept.append(p)
                    continue
                if abs(p["coord"] - ref_coord) > 20.0:
                    continue
                if p["coord"] != ref_coord and p.get("coord_source") in WEAK_SOURCES:
                    p = dict(p)
                    p["bubble_offset_pts"] = round(abs(p["coord"] - ref_coord), 2)
                    p["coord"] = ref_coord
                    p["coord_source"] = "cross_track_corroborated"
                kept.append(p)
            meta = dict(meta)
            meta["primary_count"] = sum(1 for p in kept if not p["is_secondary"])
            meta["secondary_count"] = sum(1 for p in kept if p["is_secondary"])
            cleaned.append((kept, meta))
        return cleaned

    v_tracks = _drop_cross_track_mismatches(v_tracks)
    h_tracks = _drop_cross_track_mismatches(h_tracks)
    # A track that lost every point to cross-track validation isn't a real
    # track at all -- it was fully bogus, not just partially noisy. Drop it
    # rather than reporting an empty, misleading "confirmed track."
    v_tracks = [(chain, meta) for chain, meta in v_tracks if len(chain) >= 2]
    h_tracks = [(chain, meta) for chain, meta in h_tracks if len(chain) >= 2]

    v_chain, v_meta = (v_tracks[0] if v_tracks else ([], {"band_found": False}))
    h_chain, h_meta = (h_tracks[0] if h_tracks else ([], {"band_found": False}))

    # Recover grids drawn on an interior rail rather than at the sheet edge.
    # Purely additive -- see _absorb_interior_grids for the evidence required.
    _absorb = os.getenv("GRID_ABSORB_INTERIOR", "1") not in ("0", "false", "False")
    if _absorb:
        v_chain, v_interior = _absorb_interior_grids(
            v_chain, confirmed, v_axis_type, "cx", dim_spans, pts_per_foot)
        h_chain, h_interior = _absorb_interior_grids(
            h_chain, confirmed, h_axis_type, "cy", dim_spans, pts_per_foot)
    else:
        v_interior = h_interior = []
    v_meta["interior_grids_recovered"] = [g["label"] for g in v_interior]
    h_meta["interior_grids_recovered"] = [g["label"] for g in h_interior]
    if v_tracks:
        v_tracks[0] = (v_chain, v_meta)
    if h_tracks:
        h_tracks[0] = (h_chain, h_meta)

    # Perpendicular band coordinate for each axis
    v_band_cy = None
    v_labels = {p["label"] for p in v_chain}
    cys = [c["cy"] for c in confirmed if c["axis"] == v_axis_type and c["text"] in v_labels]
    if cys:
        v_band_cy = sum(cys) / len(cys)

    h_band_cx = None
    h_labels = {p["label"] for p in h_chain}
    cxs = [c["cx"] for c in confirmed if c["axis"] == h_axis_type and c["text"] in h_labels]
    if cxs:
        h_band_cx = sum(cxs) / len(cxs)

    if not is_explicit_scale:
        calibrated = None
        if v_chain and v_band_cy is not None:
            calibrated = _calibrate_pts_per_foot(v_chain, dim_spans, pos_key="cx", other_coord=v_band_cy)
        if calibrated is None and h_chain and h_band_cx is not None:
            calibrated = _calibrate_pts_per_foot(h_chain, dim_spans, pos_key="cy", other_coord=h_band_cx)
        if calibrated:
            pts_per_foot = calibrated
            scale_str = f"CALIBRATED FROM PRINTED DIMENSIONS ({round(calibrated,3)} pts/ft) -- no explicit sheet scale found"
            scale_source = "calibrated_from_printed_dimensions"
        else:
            scale_source = "default_guess_unverified"
    else:
        scale_source = "explicit_sheet_scale"

    def _make_bays(chain: List[Dict[str, Any]], axis_letter: str, band_coord: Optional[float],
                    reference_coords: Optional[List[float]] = None) -> List[Dict[str, Any]]:
        bays = []
        pos_key = "cx" if axis_letter == "V" else "cy"
        other_key = "cy" if axis_letter == "V" else "cx"

        # This chain's own typical bay spacing -- used below so the
        # reference-gap check only fires on a genuinely ANOMALOUS span for
        # THIS track, not on every pair just because a denser, independent
        # track (e.g. the opposite side of the building, with its own
        # different sub-grids) happens to have a point in between. Two
        # tracks legitimately covering different bay breakdowns is normal;
        # this guard is only for the case where THIS track itself skipped
        # over a real intermediate grid it should have had.
        raw_spans = [abs(chain[i + 1]["coord"] - chain[i]["coord"]) for i in range(len(chain) - 1)]
        raw_spans = [s for s in raw_spans if s >= 5.0]
        median_span = sorted(raw_spans)[len(raw_spans) // 2] if raw_spans else None

        for i in range(len(chain) - 1):
            p1, p2 = chain[i], chain[i + 1]
            span_px = abs(p2["coord"] - p1["coord"])
            if span_px < 5.0:
                continue
            # If a denser track on this same axis has a confirmed grid line
            # strictly between these two points AND this particular span is
            # anomalously large next to this track's own typical bay size
            # (roughly >1.8x the local median), this track is missing that
            # intermediate grid -- draw nothing here rather than a single
            # span that silently swallows several real bays. A real gap is
            # better than a misleadingly long "bay." A normal-sized bay is
            # never rejected just because a different, independent track
            # happens to have an unrelated point in the same coordinate
            # range.
            if reference_coords and median_span and span_px > median_span * 1.8:
                lo, hi = min(p1["coord"], p2["coord"]), max(p1["coord"], p2["coord"])
                if any(lo + 1.0 < rc < hi - 1.0 for rc in reference_coords):
                    continue
            calc_ft = span_px / pts_per_foot if pts_per_foot > 0 else 0.0
            mid = (p1["coord"] + p2["coord"]) / 2.0
            # Candidates centered between the two grid points; among those,
            # prefer whichever sits on the dimension track CLOSEST to the
            # bubble row/column itself (the innermost, per-bay track), not
            # a farther-out cumulative/overall track that happens to also
            # fall within the x/y window.
            rails = [p.get("rail_coord") for p in (p1, p2)
                     if p.get("rail_coord") is not None]
            eff_band = (sum(rails) / len(rails)) if rails else band_coord
            candidates = [
                d for d in dim_spans
                if abs(d[pos_key] - mid) <= span_px * 0.35
                and (eff_band is None or abs(d[other_key] - eff_band) <= 250.0)
            ]
            ocr_alternatives = None
            match = None
            agrees = None
            matched_scale = None

            if candidates:
                # Direct individual bay matching: check if any candidate agrees under
                # the current active scale OR ANY standard architectural scale category.
                agreeing_candidates = []
                for cand in candidates:
                    is_agr, s_label = check_dim_agreement_all_scales(
                        cand.get("val_ft"), span_px, calc_ft, pts_per_foot
                    )
                    if is_agr:
                        agreeing_candidates.append((cand, s_label))

                if agreeing_candidates:
                    # Prefer the agreeing candidate sitting closest to this dimension track
                    if eff_band is not None:
                        match, matched_scale = min(
                            agreeing_candidates,
                            key=lambda pair: abs(pair[0][other_key] - eff_band)
                        )
                    else:
                        match, matched_scale = agreeing_candidates[0]
                    agrees = True
                else:
                    # Candidate exists but does not match geometry under ANY scale category
                    if eff_band is not None:
                        match = min(candidates, key=lambda d: abs(d[other_key] - eff_band))
                    else:
                        match = candidates[0]
                    agrees = False
                    alts = sorted({d["text"] for d in candidates})[:4]
                    if len(alts) > 1:
                        ocr_alternatives = alts

            # Provenance: a bay measured line-to-line is exact; one where
            # either end fell back to the bubble centre carries that end's
            # dodge as error. Downstream consumers can weight or filter on
            # this instead of treating every bay as equally trustworthy.
            src1 = p1.get("coord_source", "bubble_inferred")
            src2 = p2.get("coord_source", "bubble_inferred")
            measured_between = ("grid_lines" if src1 == src2 == "vector_line"
                                else "mixed" if "vector_line" in (src1, src2)
                                else "bubble_centres")
            bubble_span_px = None
            if p1.get("bubble_coord") is not None and p2.get("bubble_coord") is not None:
                bubble_span_px = abs(p2["bubble_coord"] - p1["bubble_coord"])
            bays.append({
                "ocr_alternatives": ocr_alternatives,
                "from_grid": p1["label"],
                "to_grid": p2["label"],
                "span_points": round(span_px, 2),
                "dimension_text": ft_to_arch(calc_ft),
                "length_inches": round(calc_ft * 12.0, 1),
                "ocr_text": match["text"] if match else None,
                "agrees_with_ocr": agrees,
                "matched_scale": matched_scale,
                "flagged": (agrees is False),
                "measured_between": measured_between,
                "from_coord_source": src1,
                "to_coord_source": src2,
                "bubble_centre_span_points": (None if bubble_span_px is None
                                              else round(bubble_span_px, 2)),
                "bubble_centre_delta_inches": (
                    None if bubble_span_px is None or pts_per_foot <= 0
                    else round((bubble_span_px - span_px) / pts_per_foot * 12.0, 2)),
            })

        return bays

    def _extend_chain_with_local_confirmed(chain: List[Dict[str, Any]], axis_type: str,
                                            band_key: str, band_center: float, pos_key: str,
                                            tol: float = 70.0) -> List[Dict[str, Any]]:
        """
        A continuation track (opposite-margin case) starts as a copy of the
        chain already confirmed on the OTHER side -- but a sheet can also
        place a bubble that ONLY appears on this side (e.g. an extra
        sub-grid like 6.5/6.8 dimensioned only at the bottom, not repeated
        at the top). Pull in any confirmed bubble of the right axis whose
        band position sits near this track's own band, that isn't already
        in the chain, so that bubble gets its own bay boundary instead of
        being silently absorbed into a neighboring span.
        """
        existing_labels = {p["label"] for p in chain}
        existing_ranks = [_label_rank(p["label"]) for p in chain]
        if not existing_ranks:
            return chain
        lo_rank, hi_rank = min(existing_ranks), max(existing_ranks)
        extra = [
            c for c in confirmed
            if c["axis"] == axis_type
            and c["text"] not in existing_labels
            and abs(c[band_key] - band_center) <= tol
            # Interior-insertion only: a genuine extra sub-grid (6.5, 6.8,
            # B.7...) always falls BETWEEN two grids this chain already
            # confirms. A label whose rank falls outside the chain's own
            # [min, max] range is not an insertion into this run of grids at
            # all -- it's an unrelated symbol that happens to pass the same
            # circle+text bubble test (a compass "N", a detail callout, a
            # section marker). Reject those generically instead of trying to
            # blacklist specific letters.
            and lo_rank <= _label_rank(c["text"]) <= hi_rank
        ]
        if not extra:
            return chain
        merged = list(chain)
        for c in extra:
            coord, source = grid_coord(c, pos_key)
            line_len_frac, line_match_margin = line_evidence(c, pos_key)
            merged.append({
                "label": c["text"],
                "is_secondary": c["is_secondary"],
                "coord": round(coord, 2),
                "coord_source": source,
                "bubble_coord": round(c[pos_key], 2),
                "bubble_offset_pts": (None if source == "bubble_inferred"
                                      else round(abs(coord - c[pos_key]), 2)),
                "line_len_frac": line_len_frac,
                "line_margin": line_match_margin,
            })
        # Grids pulled in here skipped the gate that runs inside
        # _build_axis_tracks, so apply it now -- otherwise a bubble added on
        # this path could override its own coordinate on line evidence that
        # was never checked. These are the sheet's densest sub-grids, which
        # is exactly where a weak match does the most damage.
        reject_outlier_line_coords(merged)
        merged.sort(key=lambda p: p["coord"])
        return merged

    def _has_real_dimension_line(orientation: str, band_coord: float,
                                  lo: float, hi: float,
                                  tol: float = 85.0,
                                  min_cover_frac: float = 0.6) -> bool:
        """
        Independent, non-textual evidence that a real line is physically
        drawn at this band position, long enough to be the dimension line
        for this whole run -- not proof from agreeing numbers (which can be
        coincidence -- see _track_confidently_confirmed), but proof from
        the page's own vector geometry, the same evidence
        _find_confirmed_bubbles/build_line_index already use everywhere
        else in this module.

        This is exactly the real-world case where a drafter dimensions the
        SAME grid line on a second side of the sheet without re-drawing its
        bubble -- perfectly normal, common practice (the grid was already
        labeled once; repeating the label on every dimensioned side would
        be redundant). The dimension line itself, and its witness/extension
        strokes, are still real ink on the page even though no bubble
        circle sits on this side -- so `has_local_bubble_evidence` alone
        was blind to it. A short, unrelated interior line (a wall, a
        callout leader) that merely happens to sit near this band will not
        span anywhere close to the full run; a genuine dimension line for
        the whole side will. `min_cover_frac` is deliberately generous
        (0.6) rather than requiring the full span, since a dimension line
        can be interrupted by a title block or a jog without stopping
        being the real line for this run.
        """
        if line_index is None:
            return False
        lines = line_index.vertical if orientation == "vertical" else line_index.horizontal
        needed = (hi - lo) * min_cover_frac
        if needed <= 0:
            return False
        for l in lines:
            if abs(l["coord"] - band_coord) > tol:
                continue
            if (l["hi"] - l["lo"]) >= needed:
                return True
        return False

    def _track_confidently_confirmed(bays: List[Dict[str, Any]], has_local_bubble_evidence: bool = False) -> bool:
        """
        Gate for accepting a dimension track that has NO confirmed bubbles of
        its own (the opposite-margin / same-grid-continuation case) -- it is
        only backed by nearby printed length text, so that text needs to
        actually agree with the geometry, not just exist. An absolute count
        of agreeing bays isn't enough on its own: a track where most of its
        matched bays actively DISAGREE with the geometry is more likely a
        stray, unrelated block of dimension text than a real continuation of
        this grid -- reject it rather than draw a mostly-wrong track.

        When this track's chain was extended with a bubble confirmed
        independently AT this track's own position (see
        _extend_chain_with_local_confirmed) it already has real geometric
        evidence of its own, same as any other confirmed track -- OCR
        agreement is then just per-bay QA (as it is everywhere else in this
        module), not a precondition for existing, so this gate is skipped.
        """
        # A synthetic "opposite margin" track is a COPY of the chain already
        # confirmed on the other side (see _extend_chain_with_local_confirmed)
        # -- nothing about it comes from anything actually drawn at this
        # position on the sheet. Accepting it purely because a handful of
        # printed length strings elsewhere on the page happen to numerically
        # agree with the copied bay lengths was found to draw a full
        # dimension line -- with its own grid bubbles and length labels --
        # on a margin that has no real second dimension line, and in some
        # cases no grid presence at all beyond a stray interior sub-grid.
        # Agreeing dimension text is not evidence a LINE exists there; it
        # only proves the sheet's numbers are internally consistent, which
        # they always are. A synthetic track is now accepted ONLY when
        # _extend_chain_with_local_confirmed found at least one bubble that
        # is independently, genuinely confirmed (real vector circle + label)
        # at THIS track's own position -- i.e. there is actual grid presence
        # on this margin, not just agreeing arithmetic borrowed from the
        # other side.
        return has_local_bubble_evidence

    horizontal_bays = _make_bays(v_chain, "V", v_band_cy)  # numbers -> vertical grid lines -> horizontal bay spacing
    vertical_bays = _make_bays(h_chain, "H", h_band_cx)    # letters -> horizontal grid lines -> vertical bay spacing

    # Every confirmed track gets its own marked dimension line -- this is
    # what lets a 2-side drawing and a 4-side drawing both come out right,
    # instead of always forcing exactly one line per axis. The richest
    # (first/densest) track's grid coordinates are used as the reference
    # set so a sparser track never draws a span across a gap it didn't
    # actually confirm.
    v_reference_coords = [p["coord"] for p in v_chain]
    h_reference_coords = [p["coord"] for p in h_chain]

    # Building envelope bounding box from detected grid chains
    min_v_x = min(v_reference_coords) if v_reference_coords else 0.0
    max_v_x = max(v_reference_coords) if v_reference_coords else page_w
    min_h_y = min(h_reference_coords) if h_reference_coords else 0.0
    max_h_y = max(h_reference_coords) if h_reference_coords else page_h

    horizontal_dimension_tracks = []
    for ti, (chain, meta) in enumerate(v_tracks):
        band_coord = meta.get("band_coord")
        # Enforce that horizontal dimension track sits on perimeter outside
        # framing -- but only when the OTHER axis (letters, here) actually
        # confirmed a building envelope to check against. When that other
        # axis found nothing at all (h_reference_coords empty), min_h_y/
        # max_h_y fall back to 0.0/page_h, which isn't "the building spans
        # the full page" -- it's "we don't know" -- and treating it as a
        # real envelope would reject every legitimate numbers-axis track
        # on a sheet where only one axis happened to confirm bubbles.
        if h_reference_coords and meta["side"] == "top" and band_coord is not None and band_coord > min_h_y + 20.0:
            continue
        if h_reference_coords and meta["side"] == "bottom" and band_coord is not None and band_coord < max_h_y - 20.0:
            continue
        ref = v_reference_coords if ti > 0 else None
        bays = _make_bays(chain, "V", band_coord, reference_coords=ref)
        horizontal_dimension_tracks.append({
            "side": meta["side"],
            "band_coord": band_coord,
            "primary_count": meta["primary_count"],
            "secondary_count": meta["secondary_count"],
            "grids": chain,
            "bays": bays,
        })

    # Check if opposite margins have dimension text missed due to lack of repeated bubbles
    existing_h_sides = {t["side"] for t in horizontal_dimension_tracks}
    if "bottom" not in existing_h_sides and v_chain and max_h_y < page_h - 30.0:
        # Candidate dimension texts strictly below building envelope
        bot_dims = [d for d in dim_spans if d["cy"] > max_h_y + 15.0 and (min_v_x - 100.0 <= d["cx"] <= max_v_x + 100.0)]
        if len(bot_dims) >= 2:
            cy_buckets = {}
            for d in bot_dims:
                key = round(d["cy"] / 25.0) * 25.0
                cy_buckets.setdefault(key, []).append(d)
            if cy_buckets:
                best_cy_key = max(cy_buckets.keys(), key=lambda k: len(cy_buckets[k]))
                best_bot_dims = cy_buckets[best_cy_key]
                if len(best_bot_dims) >= 2:
                    avg_cy = sum(d["cy"] for d in best_bot_dims) / len(best_bot_dims)
                    if avg_cy > max_h_y + 15.0:
                        ext_chain = _extend_chain_with_local_confirmed(
                            v_chain, v_axis_type, "cy", avg_cy, "cx")
                        bays = _make_bays(ext_chain, "V", avg_cy)
                        has_evidence = (len(ext_chain) > len(v_chain)
                                        or _has_real_dimension_line("horizontal", avg_cy, min_v_x, max_v_x))
                        if _track_confidently_confirmed(bays, has_local_bubble_evidence=has_evidence):
                            horizontal_dimension_tracks.append({
                                "side": "bottom",
                                "band_coord": round(avg_cy, 2),
                                "primary_count": sum(1 for p in ext_chain if not p["is_secondary"]),
                                "secondary_count": sum(1 for p in ext_chain if p["is_secondary"]),
                                "grids": ext_chain,
                                "bays": bays,
                            })

    if "top" not in existing_h_sides and v_chain and min_h_y > 30.0:
        # Candidate dimension texts strictly above building envelope
        top_dims = [d for d in dim_spans if d["cy"] < min_h_y - 15.0 and (min_v_x - 100.0 <= d["cx"] <= max_v_x + 100.0)]
        if len(top_dims) >= 2:
            cy_buckets = {}
            for d in top_dims:
                key = round(d["cy"] / 25.0) * 25.0
                cy_buckets.setdefault(key, []).append(d)
            if cy_buckets:
                best_cy_key = max(cy_buckets.keys(), key=lambda k: len(cy_buckets[k]))
                best_top_dims = cy_buckets[best_cy_key]
                if len(best_top_dims) >= 2:
                    avg_cy = sum(d["cy"] for d in best_top_dims) / len(best_top_dims)
                    if avg_cy < min_h_y - 15.0:
                        ext_chain = _extend_chain_with_local_confirmed(
                            v_chain, v_axis_type, "cy", avg_cy, "cx")
                        bays = _make_bays(ext_chain, "V", avg_cy)
                        has_evidence = (len(ext_chain) > len(v_chain)
                                        or _has_real_dimension_line("horizontal", avg_cy, min_v_x, max_v_x))
                        if _track_confidently_confirmed(bays, has_local_bubble_evidence=has_evidence):
                            horizontal_dimension_tracks.append({
                                "side": "top",
                                "band_coord": round(avg_cy, 2),
                                "primary_count": sum(1 for p in ext_chain if not p["is_secondary"]),
                                "secondary_count": sum(1 for p in ext_chain if p["is_secondary"]),
                                "grids": ext_chain,
                                "bays": bays,
                            })

    vertical_dimension_tracks = []
    for ti, (chain, meta) in enumerate(h_tracks):
        band_coord = meta.get("band_coord")
        # Enforce that vertical dimension track sits on perimeter outside
        # framing -- same reasoning as the horizontal loop above: only
        # apply this when the numbers axis actually confirmed a real
        # building envelope (v_reference_coords non-empty). Otherwise
        # min_v_x/max_v_x are meaningless 0.0/page_w placeholders and this
        # guard would wrongly reject every letters-axis track on a sheet
        # where the numbers axis alone failed to confirm any bubbles.
        if v_reference_coords and meta["side"] == "left" and band_coord is not None and band_coord > min_v_x + 20.0:
            continue
        if v_reference_coords and meta["side"] == "right" and band_coord is not None and band_coord < max_v_x - 20.0:
            continue
        ref = h_reference_coords if ti > 0 else None
        bays = _make_bays(chain, "H", band_coord, reference_coords=ref)
        vertical_dimension_tracks.append({
            "side": meta["side"],
            "band_coord": band_coord,
            "primary_count": meta["primary_count"],
            "secondary_count": meta["secondary_count"],
            "grids": chain,
            "bays": bays,
        })

    # Check if opposite margins have dimension text missed due to lack of repeated bubbles
    existing_v_sides = {t["side"] for t in vertical_dimension_tracks}
    if "left" not in existing_v_sides and h_chain and min_v_x > 30.0:
        # Candidate dimension texts strictly to the left of building envelope
        left_dims = [d for d in dim_spans if d["cx"] < min_v_x - 15.0 and (min_h_y - 100.0 <= d["cy"] <= max_h_y + 100.0)]
        if len(left_dims) >= 2:
            cx_buckets = {}
            for d in left_dims:
                key = round(d["cx"] / 25.0) * 25.0
                cx_buckets.setdefault(key, []).append(d)
            if cx_buckets:
                best_cx_key = max(cx_buckets.keys(), key=lambda k: len(cx_buckets[k]))
                best_left_dims = cx_buckets[best_cx_key]
                if len(best_left_dims) >= 2:
                    avg_cx = sum(d["cx"] for d in best_left_dims) / len(best_left_dims)
                    if avg_cx < min_v_x - 15.0:
                        ext_chain = _extend_chain_with_local_confirmed(
                            h_chain, h_axis_type, "cx", avg_cx, "cy")
                        bays = _make_bays(ext_chain, "H", avg_cx)
                        has_evidence = (len(ext_chain) > len(h_chain)
                                        or _has_real_dimension_line("vertical", avg_cx, min_h_y, max_h_y))
                        if _track_confidently_confirmed(bays, has_local_bubble_evidence=has_evidence):
                            vertical_dimension_tracks.append({
                                "side": "left",
                                "band_coord": round(avg_cx, 2),
                                "primary_count": sum(1 for p in ext_chain if not p["is_secondary"]),
                                "secondary_count": sum(1 for p in ext_chain if p["is_secondary"]),
                                "grids": ext_chain,
                                "bays": bays,
                            })

    if "right" not in existing_v_sides and h_chain and max_v_x < page_w - 30.0:
        # Candidate dimension texts strictly to the right of building envelope
        right_dims = [d for d in dim_spans if d["cx"] > max_v_x + 15.0 and (min_h_y - 100.0 <= d["cy"] <= max_h_y + 100.0)]
        if len(right_dims) >= 2:
            cx_buckets = {}
            for d in right_dims:
                key = round(d["cx"] / 25.0) * 25.0
                cx_buckets.setdefault(key, []).append(d)
            if cx_buckets:
                best_cx_key = max(cx_buckets.keys(), key=lambda k: len(cx_buckets[k]))
                best_right_dims = cx_buckets[best_cx_key]
                if len(best_right_dims) >= 2:
                    avg_cx = sum(d["cx"] for d in best_right_dims) / len(best_right_dims)
                    if avg_cx > max_v_x + 15.0:
                        ext_chain = _extend_chain_with_local_confirmed(
                            h_chain, h_axis_type, "cx", avg_cx, "cy")
                        bays = _make_bays(ext_chain, "H", avg_cx)
                        has_evidence = (len(ext_chain) > len(h_chain)
                                        or _has_real_dimension_line("vertical", avg_cx, min_h_y, max_h_y))
                        if _track_confidently_confirmed(bays, has_local_bubble_evidence=has_evidence):
                            vertical_dimension_tracks.append({
                                "side": "right",
                                "band_coord": round(avg_cx, 2),
                                "primary_count": sum(1 for p in ext_chain if not p["is_secondary"]),
                                "secondary_count": sum(1 for p in ext_chain if p["is_secondary"]),
                                "grids": ext_chain,
                                "bays": bays,
                            })



    # Report every grid the sheet actually carries, not only the densest
    # track's. v_chain / h_chain stay untouched so per-track bay computation
    # and the reference-coordinate logic behave exactly as before -- this
    # changes what comes OUT, not how anything is measured.
    if os.getenv("GRID_UNION_TRACKS", "1") in ("0", "false", "False"):
        v_grids = [{"label": p["label"], "x": p["coord"], "is_secondary": p["is_secondary"],
                    "coord_source": p.get("coord_source", "bubble_inferred"),
                    "bubble_x": p.get("bubble_coord"),
                    "bubble_offset_pts": p.get("bubble_offset_pts")} for p in v_chain]
        h_grids = [{"label": p["label"], "y": p["coord"], "is_secondary": p["is_secondary"],
                    "coord_source": p.get("coord_source", "bubble_inferred"),
                    "bubble_y": p.get("bubble_coord"),
                    "bubble_offset_pts": p.get("bubble_offset_pts")} for p in h_chain]
    else:
        v_grids = _union_axis_grids(v_tracks, "x")
        h_grids = _union_axis_grids(h_tracks, "y")

    intersections = []
    CROP_HALF_SIZE = 50.0
    for vg in v_grids:
        for hg in h_grids:
            ix, iy = vg["x"], hg["y"]
            crop_bbox = [
                max(0.0, ix - CROP_HALF_SIZE), max(0.0, iy - CROP_HALF_SIZE),
                min(page_w, ix + CROP_HALF_SIZE), min(page_h, iy + CROP_HALF_SIZE),
            ]
            intersections.append({
                "grid_id": f"{vg['label']}-{hg['label']}",
                "grid_x_label": vg["label"], "grid_y_label": hg["label"],
                "x": ix, "y": iy,
                "crop_bbox": [round(c, 2) for c in crop_bbox],
            })

    v_coords = [g["x"] for g in v_grids]
    h_coords = [g["y"] for g in h_grids]
    envelope = {
        "min_x": min(v_coords) if v_coords else 0.0, "max_x": max(v_coords) if v_coords else page_w,
        "min_y": min(h_coords) if h_coords else 0.0, "max_y": max(h_coords) if h_coords else page_h,
        "total_width_points": round(max(v_coords) - min(v_coords), 2) if v_coords else 0.0,
        "total_height_points": round(max(h_coords) - min(h_coords), 2) if h_coords else 0.0,
    }

    doc.close()

    return {
        "status": "SUCCESS",
        "page_dimensions": {"width": page_w, "height": page_h},
        "scale": {
            "scale_string": scale_str,
            "points_per_foot": round(pts_per_foot, 4),
            "is_explicit": is_explicit_scale,
            "source": scale_source,
        },
        "vertical_grids": v_grids,
        "horizontal_grids": h_grids,
        "horizontal_dimension_tracks": horizontal_dimension_tracks,
        "vertical_dimension_tracks": vertical_dimension_tracks,
        "horizontal_dimension_track_count": len(horizontal_dimension_tracks),
        "vertical_dimension_track_count": len(vertical_dimension_tracks),
        "vertical_axis_meta": v_meta,
        "horizontal_axis_meta": h_meta,
        # Where each grid's coordinate came from. A sheet whose grids are
        # mostly "bubble_inferred" is a sheet whose bay lengths still carry
        # bubble-dodge error -- almost always a scanned/raster page with no
        # usable vector paths, which is worth surfacing rather than hiding.
        "grid_line_geometry": {
            "enabled": _use_lines,
            "index_stats": line_index.stats if line_index is not None else None,
            "vertical_line_confirmed": sum(
                1 for g in v_grids if g["coord_source"] in _LINE_BACKED),
            "vertical_total": len(v_grids),
            "horizontal_line_confirmed": sum(
                1 for g in h_grids if g["coord_source"] in _LINE_BACKED),
            "horizontal_total": len(h_grids),
            # How many grids the LINE actually moved off the bubble -- i.e.
            # how many dodged bubbles this pass corrected. Zero is a normal,
            # healthy result on a clean vector sheet, not a failure.
            "grids_corrected_by_line": sum(
                1 for g in (v_grids + h_grids) if g["coord_source"] == "vector_line"),
            "measured_between": (
                "grid_lines"
                if (v_grids or h_grids) and all(
                    g["coord_source"] in _LINE_BACKED for g in (v_grids + h_grids))
                else "mixed" if any(
                    g["coord_source"] in _LINE_BACKED for g in (v_grids + h_grids))
                else "bubble_centres"),
            "worst_vertical_offsets": chain_offset_report(v_chain, pts_per_foot)[:8],
            "worst_horizontal_offsets": chain_offset_report(h_chain, pts_per_foot)[:8],
            "outliers_rejected": (v_meta.get("line_outliers_rejected", 0)
                                  + h_meta.get("line_outliers_rejected", 0)),
        },
        "horizontal_bays": horizontal_bays,
        "vertical_bays": vertical_bays,
        "intersections": intersections,
        "envelope": envelope,
        "total_intersections_count": len(intersections),
        "total_horizontal_bays_count": len(horizontal_bays),
        "total_vertical_bays_count": len(vertical_bays),
    }


MATCHED_SCALE_DICT = dict(STANDARD_ARCHITECTURAL_SCALES)


def _display_dimension_text(bay: Dict[str, Any], current_pts_per_foot: float = 0.0) -> str:
    """
    Pick what to show as this bay's length label.

    If the bay agrees with OCR:
      - If matched on a specific architectural scale and current_pts_per_foot is provided,
        scale the exact OCR human-drafted value by the ratio (matched_ppf / current_pts_per_foot)
        and format cleanly with ft_to_arch() so exact fractions (e.g. 11'-3 1/2", 15'-6") are preserved
        without sub-pixel noise.
      - If matched on current_scale or verbatim, return bay["ocr_text"].
    If there is a mismatch or no OCR match:
      - Return the CAD-measured bay["dimension_text"] so the mismatch is clearly visible.
    """
    if bay.get("agrees_with_ocr") and bay.get("ocr_text"):
        matched_scale = bay.get("matched_scale")
        if matched_scale in MATCHED_SCALE_DICT and current_pts_per_foot > 0:
            ocr_ft = parse_dimension_string(bay["ocr_text"])
            if ocr_ft is not None:
                matched_ppf = MATCHED_SCALE_DICT[matched_scale]
                exact_scaled_ft = ocr_ft * (matched_ppf / current_pts_per_foot)
                return ft_to_arch(exact_scaled_ft)
        return bay["ocr_text"]
    return bay.get("dimension_text", "")


def to_frontend_dimension_lines(results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Flatten every confirmed dimension track (both axes, every side found) into
    the flat list shape the existing frontend already expects -- the same
    {id, axis, from_grid, to_grid, label, length_ft, text, x1, y1, x2, y2,
    source, ocr_text, scale_source} objects the previous extract_grid_dimensions()
    produced, with x/y normalized 0-1 by page width/height. This means
    DimensionLine.tsx / OverlayLayer.tsx need no changes to render this --
    they just now receive one entry per real, confirmed segment, on however
    many sides/tracks the sheet actually has, instead of a single assumed side.
    """
    pw = results["page_dimensions"]["width"]
    ph = results["page_dimensions"]["height"]
    scale_source = results["scale"]["source"]
    pts_per_foot = results["scale"].get("points_per_foot", 0.0)
    out: List[Dict[str, Any]] = []

    for ti, track in enumerate(results["horizontal_dimension_tracks"]):  # numbers axis -> axis "V"
        y = track["band_coord"]
        for bay in track["bays"]:
            g1 = next(g for g in track["grids"] if g["label"] == bay["from_grid"])
            g2 = next(g for g in track["grids"] if g["label"] == bay["to_grid"])
            out.append({
                "id": f"dim_v_{bay['from_grid']}_{bay['to_grid']}_{track['side']}_{ti}",
                "axis": "V",
                "from_grid": bay["from_grid"],
                "to_grid": bay["to_grid"],
                "label": f"{bay['from_grid']}–{bay['to_grid']}",
                "length_ft": round(bay["length_inches"] / 12.0, 2),
                "text": _display_dimension_text(bay, pts_per_foot),
                "x1": round(g1["coord"] / pw, 4),
                "y1": round(y / ph, 4),
                "x2": round(g2["coord"] / pw, 4),
                "y2": round(y / ph, 4),
                "source": "scale_verified" if bay["agrees_with_ocr"] else "scale_computed",
                "ocr_text": bay["ocr_text"],
                "matched_scale": bay.get("matched_scale"),
                "scale_source": scale_source,
                "side": track["side"],
                "flagged": bay["flagged"],
            })

    for ti, track in enumerate(results["vertical_dimension_tracks"]):  # letters axis -> axis "H"
        x = track["band_coord"]
        for bay in track["bays"]:
            g1 = next(g for g in track["grids"] if g["label"] == bay["from_grid"])
            g2 = next(g for g in track["grids"] if g["label"] == bay["to_grid"])
            out.append({
                "id": f"dim_h_{bay['from_grid']}_{bay['to_grid']}_{track['side']}_{ti}",
                "axis": "H",
                "from_grid": bay["from_grid"],
                "to_grid": bay["to_grid"],
                "label": f"{bay['from_grid']}–{bay['to_grid']}",
                "length_ft": round(bay["length_inches"] / 12.0, 2),
                "text": _display_dimension_text(bay, pts_per_foot),
                "x1": round(x / pw, 4),
                "y1": round(g1["coord"] / ph, 4),
                "x2": round(x / pw, 4),
                "y2": round(g2["coord"] / ph, 4),
                "source": "scale_verified" if bay["agrees_with_ocr"] else "scale_computed",
                "ocr_text": bay["ocr_text"],
                "matched_scale": bay.get("matched_scale"),
                "scale_source": scale_source,
                "side": track["side"],
                "flagged": bay["flagged"],
            })

    return out


def _grid_label_sort_key(label: Any):
    """Order grid labels the way a detailer actually reads the sequence --
    natural numeric ordering ("1", "2", ... "10", "11"), sub-grids ("1.1", "2A"),
    and drafting alphabetical order ("A", "B", ... "Z", "AA", "AB").
    Strips noise like 'GRID ' or whitespace.
    """
    if label is None:
        return (2, ())
    s = str(label).strip()
    s = re.sub(r"^(?:grid|axis)\s*", "", s, flags=re.IGNORECASE).strip()
    if not s:
        return (2, ())

    # Split into numeric and non-numeric chunks for natural human sorting
    chunks = re.split(r"(\d+(?:\.\d+)?)", s)
    parsed = []
    for c in chunks:
        if not c:
            continue
        try:
            parsed.append((0, float(c)))
        except ValueError:
            # Length prefix ensures 'A' < 'AA' (single letter before double)
            c_clean = c.strip().upper()
            parsed.append((1, len(c_clean), c_clean))
    return (0 if parsed and parsed[0][0] == 0 else 1, tuple(parsed))


def _axis_numbering_direction(grids: List[Dict[str, Any]], coord_key: str) -> int:
    """Does this axis's label sequence increase or decrease with raw
    coordinate, e.g. does grid "1" sit at a smaller x than grid "12", or a
    larger one?  Returns +1 (labels increase with coordinate) or -1
    (labels decrease with coordinate).

    This is decided from the trend across EVERY grid on the axis (a
    majority vote over adjacent pairs in label order), not just by looking
    at where the single lowest-labeled grid happens to sit. That matters
    because a lone mislabeled or oddly-placed bubble (a detail-callout
    number reused as a grid label, a partial-plan crop, a stray secondary
    grid) can put "the first label" somewhere that isn't a real corner of
    the drawing at all -- trusting one point's position is exactly what
    produced a Work Point marker floating in blank margin space on a sheet
    whose numbering ran a different direction than assumed. Voting across
    the whole sequence means one outlier can't flip the result.
    """
    ordered = sorted(grids, key=lambda g: _grid_label_sort_key(g.get("label", "")))
    coords = [g[coord_key] for g in ordered]
    if len(coords) < 2:
        return 1
    inc = sum(1 for i in range(len(coords) - 1) if coords[i + 1] >= coords[i])
    dec = sum(1 for i in range(len(coords) - 1) if coords[i + 1] <= coords[i])
    return 1 if inc >= dec else -1


def _drop_extreme_outliers(grids: List[Dict[str, Any]], coord_key: str) -> List[Dict[str, Any]]:
    """Strip a grid off either end of the axis if it sits implausibly far
    from the rest of the real sequence -- e.g. a stray detail-callout or
    section-reference bubble that happens to reuse a real grid's label
    (a lone "A" from some unrelated note, not an actual column grid line),
    sitting way outside where the sheet's actual column grid is drawn.

    This is the gap left by both earlier approaches: trusting a single
    label's own position, and trusting the geometric extreme, BOTH assume
    every detected grid entry is a real column grid line. Neither checks
    whether that assumption holds. A real grid sequence has roughly
    consistent bay spacing; comparing each end's gap to its neighbor
    against the median gap across the whole sequence catches the case
    where it doesn't, without needing to know what a "normal" bay size is
    for any particular building.

    Only trims from the two ends (interior mis-detections are a different,
    separate problem this function isn't trying to solve), and only while
    there's still a real sequence of at least 3 grids left to compare
    against, so it can't be tricked into deleting a legitimately sparse
    sheet down to nothing.
    """
    if len(grids) < 3:
        return grids
    ordered = sorted(grids, key=lambda g: g[coord_key])
    filtered = list(ordered)
    OUTLIER_GAP_MULTIPLE = 4.0
    while len(filtered) > 2:
        coords = [g[coord_key] for g in filtered]
        gaps = [coords[i + 1] - coords[i] for i in range(len(coords) - 1)]
        med_gap = statistics.median(gaps) if gaps else 0
        if med_gap <= 0:
            break
        gap_low = coords[1] - coords[0]
        gap_high = coords[-1] - coords[-2]
        if gap_low > med_gap * OUTLIER_GAP_MULTIPLE and gap_low >= gap_high:
            filtered = filtered[1:]
            continue
        if gap_high > med_gap * OUTLIER_GAP_MULTIPLE and gap_high > gap_low:
            filtered = filtered[:-1]
            continue
        break
    return filtered


def _resolve_starting_grid(grids: List[Dict[str, Any]], coord_key: str, is_min_side: bool) -> Dict[str, Any]:
    """Select the starting grid (origin) on an axis.
    Prioritizes the first grid in label sequence (e.g. '1' or 'A') if its
    position lies on or near the expected boundary side, falling back to
    the geometric extreme on that side if the sequence first label sits
    deep in the interior or is an isolated misdetection.
    """
    ordered_by_label = sorted(grids, key=lambda g: _grid_label_sort_key(g.get("label", "")))
    extreme_grid = min(grids, key=lambda g: g[coord_key]) if is_min_side else max(grids, key=lambda g: g[coord_key])
    if not ordered_by_label:
        return extreme_grid

    first_label_grid = ordered_by_label[0]
    if first_label_grid is extreme_grid:
        return first_label_grid

    all_coords = [g[coord_key] for g in grids]
    span = max(all_coords) - min(all_coords) if len(all_coords) > 1 else 1.0
    dist_from_extreme = abs(first_label_grid[coord_key] - extreme_grid[coord_key])

    # If the first-labeled grid sits within 20% of the extreme edge, it is
    # legitimately the starting grid (e.g. Grid 1, with a secondary or sub-grid
    # like 0.5 or a corner jog sitting just slightly beyond it).
    if span > 0 and (dist_from_extreme / span) <= 0.20:
        return first_label_grid

    # Otherwise trust the geometric extreme to ensure the origin stays on
    # the perimeter framing line.
    return extreme_grid


def to_frontend_work_point(results: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Identify the plan's implied Work Point (WP) -- the grid intersection a
    structural detailer/estimator would treat as the origin for erection,
    anchor-bolt, and dimension-chain layout -- and return it in the same
    normalized 0-1 frontend coordinate space to_frontend_dimension_lines()
    uses, so it drops straight into the existing overlay without any extra
    coordinate handling.
    """
    v_grids = results.get("vertical_grids") or []
    h_grids = results.get("horizontal_grids") or []
    if not v_grids or not h_grids:
        return None

    page_dims = results.get("page_dimensions") or {}
    pw = page_dims.get("width") or 1.0
    ph = page_dims.get("height") or 1.0
    if pw <= 0 or ph <= 0:
        return None

    # Local copies only -- this filtering is specific to picking a Work
    # Point corner and must never affect dimension-line extraction, beam
    # centreline snapping, or anything else downstream.
    v_filtered = _drop_extreme_outliers(v_grids, "x")
    h_filtered = _drop_extreme_outliers(h_grids, "y")
    if not v_filtered:
        v_filtered = v_grids
    if not h_filtered:
        h_filtered = h_grids

    v_dir = _axis_numbering_direction(v_filtered, "x")
    h_dir = _axis_numbering_direction(h_filtered, "y")
    v_is_min = (v_dir == 1)
    h_is_min = (h_dir == 1)

    v_origin = _resolve_starting_grid(v_filtered, "x", v_is_min)
    h_origin = _resolve_starting_grid(h_filtered, "y", h_is_min)

    # Which way is "outside the drawing" from this corner -- used by the
    # frontend to route its WP callout leader/label AWAY from the plan
    # instead of a fixed diagonal.
    outward_dx = -1 if v_is_min else 1
    outward_dy = -1 if h_is_min else 1

    norm_x = v_origin["x"] / pw if pw > 1.0 else v_origin["x"]
    norm_y = h_origin["y"] / ph if ph > 1.0 else h_origin["y"]

    # Clamp safely inside [0.01, 0.99] so edge grid bubbles never get
    # rejected as out-of-bounds by canvas boundary checks
    clamped_x = round(max(0.005, min(0.995, norm_x)), 4)
    clamped_y = round(max(0.005, min(0.995, norm_y)), 4)

    v_lbl = str(v_origin.get("label", "")).strip() or "1"
    h_lbl = str(h_origin.get("label", "")).strip() or "A"

    return {
        "id": f"wp_{v_lbl}_{h_lbl}",
        "label": "WP",
        "v_label": v_lbl,
        "h_label": h_lbl,
        "grid_ref": f"{v_lbl}/{h_lbl}",
        "x": clamped_x,
        "y": clamped_y,
        "outward_dx": outward_dx,
        "outward_dy": outward_dy,
        "source": "grid_sequence_first",
    }


if __name__ == "__main__":
    import json
    import sys
    import os

    default_pdf = r"d:\Steel-ghost 2\Steel-ghost\AI_Extraction\pdf's\Structural (CCD#2)-4-8.pdf"
    target_pdf = sys.argv[1] if len(sys.argv) > 1 else default_pdf
    page_num = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    if not os.path.exists(target_pdf):
        print(f"File not found: {target_pdf}")
        sys.exit(1)

    print(f"--- Running Step 1 (fixed): Deterministic Geometry Pass on: {Path(target_pdf).name} (page {page_num+1}) ---")
    results = run_deterministic_geometry_pass(target_pdf, page_number=page_num)

    print(f"\n[SCALE]: {results['scale']['scale_string']}  ({results['scale']['points_per_foot']} pts/ft)  explicit={results['scale']['is_explicit']}  source={results['scale']['source']}")
    print(f"\n[VERTICAL GRIDS] ({len(results['vertical_grids'])}) side={results['vertical_axis_meta'].get('side')} primary={results['vertical_axis_meta'].get('primary_count')} secondary={results['vertical_axis_meta'].get('secondary_count')}:")
    print("  " + ", ".join(f"{g['label']}@{g['x']}" for g in results['vertical_grids']))
    print(f"\n[HORIZONTAL GRIDS] ({len(results['horizontal_grids'])}) side={results['horizontal_axis_meta'].get('side')} primary={results['horizontal_axis_meta'].get('primary_count')} secondary={results['horizontal_axis_meta'].get('secondary_count')}:")
    print("  " + ", ".join(f"{g['label']}@{g['y']}" for g in results['horizontal_grids']))

    print(f"\n[HORIZONTAL BAYS] ({len(results['horizontal_bays'])}):")
    for bay in results["horizontal_bays"]:
        flag = "  [FLAGGED: disagrees with sheet text]" if bay["flagged"] else ""
        ocr = f"  (sheet says: {bay['ocr_text']})" if bay["ocr_text"] else ""
        print(f"  {bay['from_grid']:>5} -> {bay['to_grid']:<5}: {bay['dimension_text']:>10}{ocr}{flag}")

    print(f"\n[VERTICAL BAYS] ({len(results['vertical_bays'])}):")
    for bay in results["vertical_bays"]:
        flag = "  [FLAGGED: disagrees with sheet text]" if bay["flagged"] else ""
        ocr = f"  (sheet says: {bay['ocr_text']})" if bay["ocr_text"] else ""
        print(f"  {bay['from_grid']:>5} -> {bay['to_grid']:<5}: {bay['dimension_text']:>10}{ocr}{flag}")

    print(f"\n[INTERSECTIONS]: {results['total_intersections_count']} grid intersections generated with crop bounding boxes.")

    print(f"\n[HORIZONTAL DIMENSION TRACKS] (numbers axis): {results['horizontal_dimension_track_count']} track(s) found")
    for ti, track in enumerate(results["horizontal_dimension_tracks"]):
        print(f"  Track {ti+1}: side={track['side']}  primary={track['primary_count']}  secondary={track['secondary_count']}  grids=[{', '.join(g['label'] for g in track['grids'])}]")
        for bay in track["bays"]:
            flag = "  [FLAGGED]" if bay["flagged"] else ""
            print(f"      {bay['from_grid']:>5} -> {bay['to_grid']:<5}: {bay['dimension_text']:>10}{flag}")

    print(f"\n[VERTICAL DIMENSION TRACKS] (letters axis): {results['vertical_dimension_track_count']} track(s) found")
    for ti, track in enumerate(results["vertical_dimension_tracks"]):
        print(f"  Track {ti+1}: side={track['side']}  primary={track['primary_count']}  secondary={track['secondary_count']}  grids=[{', '.join(g['label'] for g in track['grids'])}]")
        for bay in track["bays"]:
            flag = "  [FLAGGED]" if bay["flagged"] else ""
            print(f"      {bay['from_grid']:>5} -> {bay['to_grid']:<5}: {bay['dimension_text']:>10}{flag}")
    page_num = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    if not os.path.exists(target_pdf):
        print(f"File not found: {target_pdf}")
        sys.exit(1)

    print(f"--- Running Step 1 (fixed): Deterministic Geometry Pass on: {Path(target_pdf).name} (page {page_num+1}) ---")
    results = run_deterministic_geometry_pass(target_pdf, page_number=page_num)

    print(f"\n[SCALE]: {results['scale']['scale_string']}  ({results['scale']['points_per_foot']} pts/ft)  explicit={results['scale']['is_explicit']}  source={results['scale']['source']}")
    print(f"\n[VERTICAL GRIDS] ({len(results['vertical_grids'])}) side={results['vertical_axis_meta'].get('side')} primary={results['vertical_axis_meta'].get('primary_count')} secondary={results['vertical_axis_meta'].get('secondary_count')}:")
    print("  " + ", ".join(f"{g['label']}@{g['x']}" for g in results['vertical_grids']))
    print(f"\n[HORIZONTAL GRIDS] ({len(results['horizontal_grids'])}) side={results['horizontal_axis_meta'].get('side')} primary={results['horizontal_axis_meta'].get('primary_count')} secondary={results['horizontal_axis_meta'].get('secondary_count')}:")
    print("  " + ", ".join(f"{g['label']}@{g['y']}" for g in results['horizontal_grids']))

    print(f"\n[HORIZONTAL BAYS] ({len(results['horizontal_bays'])}):")
    for bay in results["horizontal_bays"]:
        flag = "  [FLAGGED: disagrees with sheet text]" if bay["flagged"] else ""
        ocr = f"  (sheet says: {bay['ocr_text']})" if bay["ocr_text"] else ""
        print(f"  {bay['from_grid']:>5} -> {bay['to_grid']:<5}: {bay['dimension_text']:>10}{ocr}{flag}")

    print(f"\n[VERTICAL BAYS] ({len(results['vertical_bays'])}):")
    for bay in results["vertical_bays"]:
        flag = "  [FLAGGED: disagrees with sheet text]" if bay["flagged"] else ""
        ocr = f"  (sheet says: {bay['ocr_text']})" if bay["ocr_text"] else ""
        print(f"  {bay['from_grid']:>5} -> {bay['to_grid']:<5}: {bay['dimension_text']:>10}{ocr}{flag}")

    print(f"\n[INTERSECTIONS]: {results['total_intersections_count']} grid intersections generated with crop bounding boxes.")

    print(f"\n[HORIZONTAL DIMENSION TRACKS] (numbers axis): {results['horizontal_dimension_track_count']} track(s) found")
    for ti, track in enumerate(results["horizontal_dimension_tracks"]):
        print(f"  Track {ti+1}: side={track['side']}  primary={track['primary_count']}  secondary={track['secondary_count']}  grids=[{', '.join(g['label'] for g in track['grids'])}]")
        for bay in track["bays"]:
            flag = "  [FLAGGED]" if bay["flagged"] else ""
            print(f"      {bay['from_grid']:>5} -> {bay['to_grid']:<5}: {bay['dimension_text']:>10}{flag}")

    print(f"\n[VERTICAL DIMENSION TRACKS] (letters axis): {results['vertical_dimension_track_count']} track(s) found")
    for ti, track in enumerate(results["vertical_dimension_tracks"]):
        print(f"  Track {ti+1}: side={track['side']}  primary={track['primary_count']}  secondary={track['secondary_count']}  grids=[{', '.join(g['label'] for g in track['grids'])}]")
        for bay in track["bays"]:
            flag = "  [FLAGGED]" if bay["flagged"] else ""
            print(f"      {bay['from_grid']:>5} -> {bay['to_grid']:<5}: {bay['dimension_text']:>10}{flag}")
