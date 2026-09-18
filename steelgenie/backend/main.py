import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import fitz
import re
import math
import time
import base64
import os
import io
import json
import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image as PILImage, ImageEnhance, ImageFilter

# ── Column Validation Engine: structural-context scoring gate for column
#    candidates (grid intersection, footing/column classification, mark
#    match, beam connectivity, schedule corroboration). Pure/no heavy deps,
#    safe to import at module load rather than lazily. ────────────────────
from app.engineering import column_validation_engine

# ── OpenCV-based raster beam line detector ───────────────────────────────────
try:
    from detection_cv import detect_beam_lines_raster as _detect_beam_lines_raster
    _RASTER_HOUGH_AVAILABLE = True
    print("[INIT] detection_cv.detect_beam_lines_raster loaded")
except Exception as _e:
    _RASTER_HOUGH_AVAILABLE = False
    print(f"[INIT] detection_cv not available — raster Hough disabled: {_e}")

# ── Brace extraction engine ───────────────────────────────────────────────────
try:
    from brace_classifier import (
        extract_diagonals        as _brace_extract_diagonals,
        classify_page_context    as _brace_classify_context,
        find_scale_annotations   as _brace_find_scales,
        classify                 as _brace_classify,
        scale_to_pts_per_foot    as _brace_ppf,
        extract_structural_nodes as _brace_extract_nodes,
        extract_opening_regions  as _brace_extract_openings,
        enrich_brace_results     as _brace_enrich,
    )
    _BRACE_EXTRACTION_AVAILABLE = True
    print("[INIT] brace_classifier loaded")
except Exception as _e:
    _BRACE_EXTRACTION_AVAILABLE = False
    print(f"[INIT] brace_classifier not available: {_e}")

# Feature flag — set BRACE_EXTRACTION=1 in environment to enable.
# Default OFF so existing workflows are unaffected until real-world
# production data has been collected.
_BRACE_EXTRACTION_ENABLED = (
    _BRACE_EXTRACTION_AVAILABLE and
    os.getenv("BRACE_EXTRACTION", "0").strip() == "1"
)
print(f"[INIT] Brace extraction: {'ENABLED' if _BRACE_EXTRACTION_ENABLED else 'DISABLED'}")

# ── Load Environment ──────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ENV_PATH = os.path.join(BASE_DIR, ".env")
    if os.path.exists(ENV_PATH):
        load_dotenv(dotenv_path=ENV_PATH, override=True)
        print("[INIT] .env loaded")
    else:
        print("[INIT] .env not found")
except ImportError:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ── Database ──────────────────────────────────────────────────────────────────
supabase_client = None
try:
    from supabase import create_client as _sb_create
    _url = os.getenv("SUPABASE_URL")
    _key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if _url and _key:
        supabase_client = _sb_create(_url, _key)
        print("[INIT] Supabase ready")
except Exception as e:
    print(f"[INIT] Supabase error: {e}")

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── Constants ─────────────────────────────────────────────────────────────────
MEMBER_COLORS = {
    "beam":   "#EC4899",
    "column": "#3B82F6",
    "brace":  "#F59E0B",
    "joist":  "#06B6D4",
    # Stage 3 (2026-07-17 rebuild): footing outline, distinct from the
    # column it carries -- neutral grey so it doesn't compete visually
    # with the blue column mark now drawn at the same location.
    "footing": "#6B7280",
}

JOIST_PATTERNS = [
    # Standard K-series joists: 14K3, 18K5, 24K7, 2K55, etc.
    r'(?<![A-Z0-9])\d{1,2}K\d+(?![A-Z0-9])',
    # Longspan / Deep Longspan joists: 28LH08, 44DLH12
    r'(?<![A-Z0-9])\d{1,2}(?:LH|DLH)\d+(?![A-Z0-9])',
    # Special K-series joists: 24KSP, 16KSP
    r'(?<![A-Z0-9])\d{1,2}KSP(?![A-Z0-9])',
    # Joist Girders: 36G9N12K, 40G10N14K
    r'(?<![A-Z0-9])\d{1,2}G\d+N[\d.]+K(?![A-Z0-9])',
    # Composite / CS Joists: 20CS3, 16CJ4
    r'(?<![A-Z0-9])\d{1,2}(?:CJ|CS)\d+(?![A-Z0-9])',
]

STEEL_PATTERNS = [
    # W-sections: depth 1-2 digits, weight 2-3 digits (all real W shapes ≥ W4X13).
    # Allows optional spaces around X: "W16X31", "W16 X 31", "W 16 X 31"
    r'W\s*\d{1,2}\s*[Xx]\s*\d{2,3}(?!\d)',
    # Abbreviated W-sections (depth only, no weight) — drawings that label beams as "W12", "W16"
    r'(?<![A-Z0-9])W\s*\d{1,2}(?![Xx\d])',
    r'HSS\s*[\d.]+\s*[Xx]\s*[\d.]+(?:\s*[Xx]\s*[\d.]+(?:/[\d.]+)?|\s*/\s*[\d.]+)?',  # HSS6X6, HSS6X6X1/4
    r'WT\s*\d{1,2}\s*[Xx]\s*\d{1,3}',
    r'HP\s*\d{1,2}\s*[Xx]\s*\d{2,3}',
    r'L\s*\d+\s*[Xx]\s*\d+(?:\s*[Xx]\s*[\d./]+)?',
    r'C\s*\d+\s*[Xx]\s*[\d.]+',
    r'MC\s*\d+\s*[Xx]\s*[\d.]+',
    r'ISA\s*[\dXx]+',
    r'PIPE\s*[\d.]+',
    # SJI Joists (K, LH, DLH, JG, KSP)
    *JOIST_PATTERNS,
]

# Grid-letter labels. Beyond a single letter (A, B, C…) real drawings also
# use two conventions this used to miss entirely (found on this project's
# binder, sheet 35 / index 34 — a "match line" partial-zone sheet):
#   • doubled letters once the alphabet runs out: AA, BB, CC, DD, EE…
#     (never two DIFFERENT letters — that would start matching ordinary
#     words like "TO", "IN", "NO", "OF" that happen to sit near the plan
#     edge, so the backreference \1? deliberately only allows a letter
#     followed by ITSELF)
#   • prime marks for offset/secondary grid lines: C', D', F'5 (letter,
#     optional subgrid ".N", optional prime, optional trailing digit)
_GRID_LETTER = re.compile(r"^([A-Z])\1?(\.\d+)?('\d*)?$")
_GRID_NUMBER  = re.compile(r'^\d+(\.\d+)?$')

# Max distance (PDF points) between a profile label and a column symbol.
# Used for the one-to-one greedy symbol→profile matching in build_members.
SYMBOL_ASSOC_RADIUS = 65   # search radius for matching symbol to nearest label
SYMBOL_SNAP_RADIUS  = 110  # snap marker TO symbol position (wider — position only)

# Grid-intersection classification tolerance.
# Reduced from 35 → 20: beam labels that sit close to (but not at) a grid crossing
# were being falsely promoted to columns by TIER 2.  20 pt ≈ 0.28″ — tight enough
# to cover typical label offsets while excluding beams that frame INTO a column.
GRID_TOL = 20
# Grid-intersection SNAP radius (for marker placement — wider than classification)
GRID_SNAP_RADIUS = 50

# Unlabeled-beam column-gate PERPENDICULAR tolerance (pt).  A candidate endpoint
# must sit within this distance (perpendicular to the beam) of a column grid row
# to count as "framing into a column".  Higher = more real beams recovered but
# more dimension/canopy lines admitted as false (beam?); lower = the reverse.
# Original behaviour (≈83 unlabeled) used ~36; 10 over-tightened it (dropped to 66).
# Measured sweep on the reference plan: recall plateaus at 30 pt (80 unlabeled,
# same col-gate rejection count as the original), so 30 recovers every column-
# framed beam without loosening further than needed.
UNLABELED_PERP_TOL = 30.0


# ── Scale conversion ──────────────────────────────────────────────────────────
def scale_to_pts_per_foot(scale_ratio: float) -> float:
    """
    Convert the frontend SCALE_OPTIONS ratio to PDF-points per foot.

    The frontend stores:  ratio = 12 / paper_inches_per_foot
    At 72 dpi:            pts_per_foot = 72 × paper_inches_per_foot
                                       = 72 × (12 / ratio)
                                       = 864 / ratio

    Examples
    --------
    1/8"=1'-0"  → ratio= 96 → pts_per_foot =  9.0
    3/16"=1'-0" → ratio= 64 → pts_per_foot = 13.5
    1/4"=1'-0"  → ratio= 48 → pts_per_foot = 18.0
    """
    if not scale_ratio or scale_ratio <= 0:
        return 0.0
    return 864.0 / scale_ratio


def compute_beam_span(cx: float, cy: float,
                      v_grid: list, h_grid: list,
                      pts_per_foot: float,
                      beam_dir: str = "H") -> dict | None:
    """
    Compute the beam span — both the length in feet AND the two physical
    endpoint positions (in raw PDF points) for rendering as a line overlay.

    Returns a dict:
        { "length_ft": float,
          "x1": float, "y1": float,   # start point (PDF pts)
          "x2": float, "y2": float }  # end point   (PDF pts)
    Returns None when the surrounding grid lines cannot be found.

    H-beam:  endpoints are (left_v_grid, cy) → (right_v_grid, cy)
    V-beam:  endpoints are (cx, top_h_grid)  → (cx, bottom_h_grid)
    """
    if beam_dir == "V":
        tops    = [gy for gy in h_grid if gy <= cy]
        bottoms = [gy for gy in h_grid if gy >  cy]
        if tops and bottoms:
            span_pt = min(bottoms) - max(tops)
            return {
                "length_ft": round(span_pt / pts_per_foot, 1) if pts_per_foot > 0 else 0.0,
                "x1": cx,         "y1": max(tops),
                "x2": cx,         "y2": min(bottoms),
            }
    else:  # "H" — default
        lefts  = [gx for gx in v_grid if gx <= cx]
        rights = [gx for gx in v_grid if gx >  cx]
        if lefts and rights:
            span_pt = min(rights) - max(lefts)
            return {
                "length_ft": round(span_pt / pts_per_foot, 1) if pts_per_foot > 0 else 0.0,
                "x1": max(lefts), "y1": cy,
                "x2": min(rights), "y2": cy,
            }

    return None


def _snap_to_grid_lines(x1: float, y1: float,
                        x2: float, y2: float,
                        bdir: str,
                        v_grid: list, h_grid: list,
                        snap_dist: float = 35.0) -> tuple:
    """
    Snap H/V beam endpoints to the nearest column grid line.

    Column grid lines (v_grid = vertical X positions, h_grid = horizontal Y
    positions) represent column CENTRELINES.  The beam line in the PDF often
    stops short of the centreline by half the column depth.  Snapping to the
    nearest grid line gives the true centre-to-centre structural span.

    snap_dist = 35 pt ≈ 3.9 ft at 1/8" scale — wide enough to bridge the
    half-column-depth gap PLUS any beam-face drawing offset (max ~3.5 ft
    combined), tight enough not to jump across to the wrong adjacent grid line
    (typical bay width >15 ft means the next column is always >150 pt away).

    Only EXTENDS the beam — never shortens it.
    """
    if bdir == "H" and v_grid:
        lx = min(x1, x2)   # left  endpoint X
        rx = max(x1, x2)   # right endpoint X

        # Left snap: find the nearest v_grid line to the LEFT of lx
        left_cands = [vx for vx in v_grid if lx - snap_dist <= vx < lx]
        if left_cands:
            new_lx = max(left_cands)   # closest grid left of lx
            if x1 <= x2:
                x1 = new_lx
            else:
                x2 = new_lx

        # Right snap: find the nearest v_grid line to the RIGHT of rx
        rx = max(x1, x2)   # recompute after possible left snap
        right_cands = [vx for vx in v_grid if rx < vx <= rx + snap_dist]
        if right_cands:
            new_rx = min(right_cands)
            if x1 <= x2:
                x2 = new_rx
            else:
                x1 = new_rx

    elif bdir == "V" and h_grid:
        ty = min(y1, y2)   # top    endpoint Y
        by_ = max(y1, y2)  # bottom endpoint Y

        # Top snap
        top_cands = [hy for hy in h_grid if ty - snap_dist <= hy < ty]
        if top_cands:
            new_ty = max(top_cands)
            if y1 <= y2:
                y1 = new_ty
            else:
                y2 = new_ty

        # Bottom snap
        by_ = max(y1, y2)
        bot_cands = [hy for hy in h_grid if by_ < hy <= by_ + snap_dist]
        if bot_cands:
            new_by = min(bot_cands)
            if y1 <= y2:
                y2 = new_by
            else:
                y1 = new_by

    return x1, y1, x2, y2, math.hypot(x2 - x1, y2 - y1)


def _snap_to_columns_along_axis(x1: float, y1: float,
                                x2: float, y2: float,
                                col_syms: list,
                                perp_tol: float = 30.0,
                                snap_dist: float = 50.0) -> tuple:
    """
    Snap both endpoints of a matched beam segment to the nearest column
    symbol that lies along the beam axis.

    In structural drawings the beam centreline is drawn from column FACE to
    column FACE (or even slightly short of the face).  The column I-symbol
    is placed at the column CENTRE.  This function bridges that gap so the
    extracted length equals the true centre-to-centre span.

    Parameters
    ----------
    perp_tol  : max perpendicular offset (pts) from beam axis to column centre
    snap_dist : max distance (pts) the endpoint can be FROM the column centre
                before we refuse to snap.  30 pt ≈ 2.7″ at ⅛″ scale — enough
                to cover half the depth of the deepest common column section
                while avoiding accidental jumps to an adjacent column symbol.
    """
    if not col_syms:
        return x1, y1, x2, y2, math.hypot(x2 - x1, y2 - y1)

    dx = x2 - x1
    dy = y2 - y1
    ln = math.hypot(dx, dy)
    if ln < 1.0:
        return x1, y1, x2, y2, ln

    ux, uy = dx / ln, dy / ln   # unit along beam
    px, py = -uy, ux            # unit perpendicular
    # Snap each end to the NEAREST column (within snap_dist).
    # Handles both short-drawn beams (extending to column centre) AND
    # overshooting beams (trimming back from foundation/wall to column centre).
    best_left_t  = None   # nearest column around x1  (|t| <= snap_dist)
    best_right_t = None   # nearest column around x2  (|t - ln| <= snap_dist)

    for sym in col_syms:
        cx, cy = sym["cx"], sym["cy"]
        rv = (cx - x1, cy - y1)
        t    = rv[0] * ux + rv[1] * uy
        perp = abs(rv[0] * px + rv[1] * py)

        if perp > perp_tol:
            continue   # column is not on this beam's axis

        # Left end: column within snap_dist of x1 (before or after x1)
        if abs(t) <= snap_dist and (ln - t) > 10.0:
            if best_left_t is None or abs(t) < abs(best_left_t):
                best_left_t = t

        # Right end: column within snap_dist of x2 (before or after x2)
        if abs(t - ln) <= snap_dist and t > 10.0:
            if best_right_t is None or abs(t - ln) < abs(best_right_t - ln):
                best_right_t = t

    ox1, oy1 = x1, y1   # keep original origin for right-end computation
    if best_left_t is not None:
        x1 = ox1 + best_left_t * ux
        y1 = oy1 + best_left_t * uy
    if best_right_t is not None:
        x2 = ox1 + best_right_t * ux
        y2 = oy1 + best_right_t * uy

    return x1, y1, x2, y2, math.hypot(x2 - x1, y2 - y1)


def _is_joist_pattern(x1: float, y1: float, x2: float, y2: float,
                      seg_pool: list,
                      angle_tol_deg: float = 4.0,
                      colinear_tol: float = 5.0,
                      gap_tol: float = 30.0) -> bool:
    """
    Detect whether the collinear segments along a matched beam axis form a
    JOIST PATTERN — many short, regularly-spaced segments — rather than a real
    beam (which is either a single continuous segment or a few pieces broken
    only at girder crossings).

    Joists in structural framing plans are drawn as a series of short parallel
    marks spanning the bay (e.g. 8-20 short segments with uniform gaps).  The
    W-section label (e.g. "W12X19") sits on one of these marks, and the
    collinear chaining in Pass 0 bridges all the gaps, producing one large
    false "beam" spanning the entire bay.

    Rules (all must hold to flag as joist):
      1. ≥ 4 collinear segments found along the axis within the chained span
      2. Mean gap between consecutive segments is < 3 × mean segment length
         (dense packing — beams have at most 1-3 breaks with large girder gaps)
      3. Number of gaps ≥ 3  (at least 3 interruptions along the run)

    Returns True if this looks like a joist run, False if it looks like a beam.
    """
    if not seg_pool:
        return False

    ln = math.hypot(x2 - x1, y2 - y1)
    if ln < 1.0:
        return False

    ux = (x2 - x1) / ln
    uy = (y2 - y1) / ln
    px, py = -uy, ux
    axis_ang = math.atan2(y2 - y1, x2 - x1)
    if axis_ang < 0:
        axis_ang += math.pi

    # Collect all segments that are collinear with this axis
    intervals: list = []  # (t_start, t_end) along axis
    for (sx1, sy1, sx2, sy2, _sln) in seg_pool:
        sdx, sdy = sx2 - sx1, sy2 - sy1
        sang = math.atan2(sdy, sdx)
        if sang < 0:
            sang += math.pi
        da = abs(axis_ang - sang)
        if da > math.pi / 2:
            da = math.pi - da
        if math.degrees(da) > angle_tol_deg:
            continue
        # Perp offset of both endpoints from our axis
        rv1x, rv1y = sx1 - x1, sy1 - y1
        rv2x, rv2y = sx2 - x1, sy2 - y1
        pd = min(abs(rv1x * px + rv1y * py), abs(rv2x * px + rv2y * py))
        if pd > colinear_tol:
            continue
        t1 = rv1x * ux + rv1y * uy
        t2 = rv2x * ux + rv2y * uy
        if t1 > t2:
            t1, t2 = t2, t1
        # Only count segments that fall within (or very near) the chained span
        if t2 < -gap_tol or t1 > ln + gap_tol:
            continue
        intervals.append((t1, t2))

    if len(intervals) < 4:
        return False  # too few segments — looks like a real beam (maybe 1-3 pieces)

    # Sort by start position and compute segment lengths and gap lengths
    intervals.sort(key=lambda iv: iv[0])

    seg_lengths = [max(0.0, t2 - t1) for t1, t2 in intervals]
    gaps = []
    for i in range(len(intervals) - 1):
        gap = intervals[i + 1][0] - intervals[i][1]
        if gap > 0:
            gaps.append(gap)

    if len(gaps) < 3:
        return False  # fewer than 3 gaps → broken beam, not joist

    mean_seg = sum(seg_lengths) / len(seg_lengths) if seg_lengths else 1.0
    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0

    # Joist criterion: gaps are small relative to segment length (dense packing).
    # For a real beam broken at girder crossings, gap ≈ column width ≈ 1-2 ft
    # which is often LARGER than the segment length for short infill beams.
    # For joists, gap ≈ joist spacing (1-4 ft) but with MANY gaps densely packed.
    # The key signal is having MANY gaps (≥3) with gap < 3× seg length.
    if mean_gap < mean_seg * 3.0 and len(gaps) >= 3:
        print(f"[JOIST_DETECT] Rejected joist pattern: "
              f"{len(intervals)} segs, {len(gaps)} gaps, "
              f"mean_seg={mean_seg:.1f}pt mean_gap={mean_gap:.1f}pt")
        return True

    return False


def _extend_with_thin_segs(x1: float, y1: float, x2: float, y2: float,
                           thin_segs: list,
                           angle_tol_deg: float = 4.0,
                           gap_tol: float = 30.0,
                           colinear_tol: float = 5.0) -> tuple:
    """
    Extend a matched beam segment at both ends using thin continuation segments.

    In many CAD drawings the beam centreline transitions to a hairline stroke near
    the column connection zone.  The main matching step ignores those thin strokes
    but we save them in thin_segs.  After the best thick segment is found we stretch
    it to cover any collinear thin continuations, giving the accurate
    column-face-to-column-face beam length.

    Safety constraints (prevent over-extension):
      • angle must agree within angle_tol_deg (default 4°)
      • perpendicular offset must be < colinear_tol pts (default 5 pt ≈ 0.07″)
      • gap between segments must be < gap_tol pts (default 18 pt ≈ 0.25″)
      • at most 4 passes (handles chained thin segments, e.g. 2 short pieces at one end)

    Returns (x1, y1, x2, y2, length).
    """
    if not thin_segs:
        return x1, y1, x2, y2, math.hypot(x2 - x1, y2 - y1)

    for _pass in range(4):
        dx = x2 - x1
        dy = y2 - y1
        ln = math.hypot(dx, dy)
        if ln < 1.0:
            break
        ux, uy = dx / ln, dy / ln
        px, py = -uy, ux
        ang = math.atan2(dy, dx)
        if ang < 0:
            ang += math.pi

        ext_left  = 0.0   # most-negative t on the left side (0 = no extension)
        ext_right = ln    # largest t on the right side (ln = no extension)

        for (sx1, sy1, sx2, sy2, _) in thin_segs:
            sdx, sdy = sx2 - sx1, sy2 - sy1
            sang = math.atan2(sdy, sdx)
            if sang < 0:
                sang += math.pi
            da = abs(ang - sang)
            if da > math.pi / 2:
                da = math.pi - da
            if math.degrees(da) > angle_tol_deg:
                continue

            # Perpendicular distance — both endpoints checked, take the minimum
            rv1x, rv1y = sx1 - x1, sy1 - y1
            rv2x, rv2y = sx2 - x1, sy2 - y1
            pd = min(abs(rv1x * px + rv1y * py), abs(rv2x * px + rv2y * py))
            if pd > colinear_tol:
                continue

            # Parametric projections onto our axis
            t1 = rv1x * ux + rv1y * uy
            t2 = rv2x * ux + rv2y * uy
            if t1 > t2:
                t1, t2 = t2, t1

            # Left end: thin seg reaches before our current x1 but is close to it
            if t1 < 0 and t2 >= -gap_tol:
                ext_left = min(ext_left, t1)

            # Right end: thin seg reaches past our current x2 but is close to it
            if t2 > ln and t1 <= ln + gap_tol:
                ext_right = max(ext_right, t2)

        changed = False
        ox1, oy1 = x1, y1   # keep original origin for right-end computation
        if ext_left < 0:
            x1 = ox1 + ext_left * ux
            y1 = oy1 + ext_left * uy
            changed = True
        if ext_right > ln:
            x2 = ox1 + ext_right * ux   # always relative to original origin
            y2 = oy1 + ext_right * uy
            changed = True
        if not changed:
            break

    return x1, y1, x2, y2, math.hypot(x2 - x1, y2 - y1)


def detect_beam_lines(page, profiles: list, plan_bounds: tuple,
                      pts_per_foot: float = 0.0,
                      column_symbols: list = None,
                      v_grid: list = None,
                      h_grid: list = None) -> dict:
    """
    PRIMARY beam detection: find structural centerlines in the PDF vector drawing
    and match them to steel-section text labels.

    In CAD-exported structural framing plans every beam IS drawn as a line segment
    on its centreline.  The profile label (e.g. "W24X76") sits right on — or very
    close to — that line at mid-span.

    Strategy
    --------
    1. Collect ALL line segments inside the plan boundary that are 30–650 pt long
       (any angle — H, V, or diagonal).  Diagonal beams appear in irregular
       framing plans (e.g. Area B skewed grids) and must not be excluded.
    2. For each profile label (cx, cy) find the closest line using perpendicular
       distance: project the label onto the infinite extension of each line and
       measure the distance to the closest point on the segment (±15 % extension
       so labels near span ends still match).  Accept if distance < LABEL_R.
    3. Return a dict  { profile_idx: {"x1","y1","x2","y2","dir","length_pt"} }
       for every profile that was successfully matched to a drawn line.
       dir is "H" / "V" / "D" (diagonal).
       Unmatched profiles fall back to the grid-based span calculation.

    This gives us EXACT endpoints and EXACT length from the drawing geometry —
    no grid guessing needed.
    """
    if isinstance(profiles, tuple):
        profiles = profiles[0]
    bx0, by0, bx1, by1 = plan_bounds
    # MIN_LEN = 45 pt ≈ 5 ft at 1/8" scale.
    # This filters two things:
    #  1. Real ticks / arrowheads / hatch lines (always <30 pt)
    #  2. Exploded dash segments — many CAD exporters draw dashed lines as
    #     many short SOLID segments with gaps rather than a single path with
    #     a PDF dash pattern.  Typical structural drawing dash lengths are
    #     3–30 pt, so 45 pt cleanly separates them from beam centrelines.
    # Dynamically scale MIN_LEN to allow short beams (down to 3 ft) at any scale,
    # but never drop below 15 pt to keep filtering out small hatch marks.
    MIN_LEN  = max(22, int(pts_per_foot * 2.2)) if pts_per_foot > 0 else 22
    # Cap at 80 ft using the drawing scale — prevents full-plan dimension/
    # annotation lines from being matched as beam centrelines.
    # Fall back to 700 pt (≈78 ft at 1/8") when scale is unknown.
    MAX_LEN  = int(pts_per_foot * 80) if pts_per_foot > 0 else 700
    # 180 pt: raised from 130 so labels pushed far from their beam in congested
    # or large-scale drawings (3/16", 1/4") still match.  Proximity scoring still
    # picks the closest line — a larger radius does NOT increase false matches.
    LABEL_R  = 180

    # ── Per-direction max-length guards ──────────────────────────────────────
    # MAX_H_MATCH / MAX_V_MATCH cap horizontal / vertical lines separately.
    # Primary cap = 1.5× widest structural bay — prevents full-width grid and
    # boundary lines from being matched as beam centrelines.
    # Fallback cap = 65% of plan dimension.
    # Diagonal lines use their own cap: hypot(MAX_H, MAX_V).
    def _max_bay(grid):
        sg = sorted(grid)
        if len(sg) < 2:
            return float("inf")
        return max(b - a for a, b in zip(sg, sg[1:]))
    _mb_w = _max_bay(v_grid or [])
    _mb_h = _max_bay(h_grid or [])
    
    # Floor cap: if grid detection finds only a few bubbles, _max_bay is tiny and
    # MAX_H/V_MATCH collapses — real long beams get rejected as "too long".
    # 40 ft is the safe floor for typical buildings; the 1.5× bay multiplier
    # automatically scales up for large hospitals / warehouses when grid IS detected.
    _MIN_CAP = int(pts_per_foot * 40) if pts_per_foot > 0 else 400
    MAX_H_MATCH = max(_mb_w * 1.5, _MIN_CAP) if _mb_w < float("inf") else MAX_LEN
    MAX_V_MATCH = max(_mb_h * 1.5, _MIN_CAP) if _mb_h < float("inf") else MAX_LEN
    if plan_bounds:
        _pb_w = plan_bounds[2] - plan_bounds[0]
        _pb_h = plan_bounds[3] - plan_bounds[1]
        MAX_H_MATCH = min(MAX_H_MATCH, _pb_w * 0.95)   # raised from 0.90 — edge beams
        MAX_V_MATCH = min(MAX_V_MATCH, _pb_h * 0.95)

    all_lines: list[tuple] = []   # (x1, y1, x2, y2, length)
    thin_segs: list[tuple] = []   # thin-stroke segments at beam/column junctions

    try:
        for d in page.get_drawings():
            # ── Skip dashed / dotted paths ────────────────────────────────────
            # Type A — PDF dash pattern: check that the bracket content of
            #   d["dashes"] is empty.  A solid line is "" or "[] 0" (empty
            #   bracket array).  Any content inside the brackets, e.g.
            #   "[3 3] 0", "[0.5 1.5] 0", means dashed/dotted → skip.
            #   Using regex on bracket content is more robust than exact-
            #   string comparison, which would miss variants like "[] 0.0".
            _dashes = (d.get("dashes") or "").strip()
            _da = re.match(r'\[([^\]]*)\]', _dashes)
            if _da and _da.group(1).strip():
                continue   # non-empty bracket content → dashed line

            # Type B — Exploded dashes: CAD draws each dash as a tiny SOLID
            #   segment with a gap to the next.  No dash property is set.
            #   Handled by MIN_LEN=45 (rejects segments shorter than ~5 ft).

            # Type C — Thin construction / hidden lines that carry no dash
            #   property but are drawn hairline-thin in CAD (lineweight ≤ 0.3 pt).
            #   Structural beam centrelines always have a measurable weight.
            #   Skip any path with an explicitly set width < 0.3 pt for the main
            #   matching pool — but save valid segments into thin_segs so we can
            #   extend a matched thick segment to its true column-face length.
            #   (Width = 0 or None means "default" in some exporters — keep those.)
            _lw = d.get("width") or 0
            if 0 < _lw < 0.3:
                for _item in d.get("items", []):
                    if _item[0] != "l":
                        continue
                    try:
                        _p1, _p2 = _item[1], _item[2]
                        _tln = math.hypot(abs(_p2.x - _p1.x), abs(_p2.y - _p1.y))
                        # Use a much smaller minimum than all_lines (MIN_LEN=45).
                        # Column-zone beam stubs can be very short (a few pts) but
                        # are still valid continuations.  The collinearity check in
                        # _extend_with_thin_segs keeps spurious tiny marks out.
                        if _tln < 3.0 or _tln > MAX_LEN:
                            continue
                        _tmx = (_p1.x + _p2.x) / 2
                        _tmy = (_p1.y + _p2.y) / 2
                        # 150 pt midpoint tolerance matches all_lines — catches
                        # thin column-zone stubs for edge/cantilever beams.
                        _TMID = 150
                        if not (bx0 - _TMID <= _tmx <= bx1 + _TMID and
                                by0 - _TMID <= _tmy <= by1 + _TMID):
                            continue
                        # Both endpoints must stay within plan bounds (+ tolerance).
                        # Raised to 250 pt to match all_lines _EP_TOL (wings of building).
                        _TEP = 250
                        if (min(_p1.x, _p2.x) < bx0 - _TEP or
                                max(_p1.x, _p2.x) > bx1 + _TEP):
                            continue
                        if (min(_p1.y, _p2.y) < by0 - _TEP or
                                max(_p1.y, _p2.y) > by1 + _TEP):
                            continue
                        thin_segs.append((_p1.x, _p1.y, _p2.x, _p2.y, _tln))
                    except Exception:
                        continue
                continue

            for item in d.get("items", []):
                if item[0] != "l":
                    continue
                try:
                    p1, p2 = item[1], item[2]
                    dx = abs(p2.x - p1.x)
                    dy = abs(p2.y - p1.y)
                    ln = math.hypot(dx, dy)
                    if ln < MIN_LEN or ln > MAX_LEN:
                        continue
                    # No plan_bounds filter on lines — collect from the entire page.
                    # plan_bounds is unreliable on large multi-bay drawings (the
                    # detected boundary covers only the grid-bubble region, which may
                    # be 30–50% of the actual framing extent on Area-B / hospital sheets).
                    # Label→line matching (LABEL_R) is the proximity guard; the
                    # structural length filter (MIN_LEN / MAX_LEN) removes arrows,
                    # tick marks, and title-block rules.  Cross-drawing false matches
                    # don't occur because a label in one drawing area won't be within
                    # LABEL_R of a line in a distant drawing area.
                    all_lines.append((p1.x, p1.y, p2.x, p2.y, ln))
                except Exception:
                    continue
    except Exception:
        pass

    h_c = sum(1 for (x1,y1,x2,y2,ln) in all_lines if abs(x2-x1) > abs(y2-y1)*2)
    v_c = sum(1 for (x1,y1,x2,y2,ln) in all_lines if abs(y2-y1) > abs(x2-x1)*2)
    print(f"[BEAM_LINES] H:{h_c}  V:{v_c}  Diagonal:{len(all_lines)-h_c-v_c}  "
          f"Total:{len(all_lines)}")

    result: dict[int, dict] = {}

    # Column-centreline X / Y positions for the endpoint snap (Pass 3d).
    # Both grid lines AND detected column symbols mark column centres, so a beam
    # end can land true centre-to-centre whether the column shows up as a grid
    # line or only as an I/H symbol.
    _col_snap_x = sorted(set([round(x, 1) for x in (v_grid or [])] +
                             [round(s["cx"], 1) for s in (column_symbols or [])]))
    _col_snap_y = sorted(set([round(y, 1) for y in (h_grid or [])] +
                             [round(s["cy"], 1) for s in (column_symbols or [])]))

    # ── Label → line matcher (one-to-one) ────────────────────────────────────
    # _find_best_line scores every candidate line for a label and returns the
    # best (line, score, midpoint-key).  `claimed` is a set of midpoint-keys of
    # lines already taken by a closer label, so each drawn beam line is matched
    # by AT MOST ONE label.  Without this, dense/closely-spaced parallel beams
    # (e.g. canopy framing) all grab the same nearest line, orphaning the rest
    # and leaving real beams with no marker.
    def _mid_key(lx1, ly1, lx2, ly2):
        # ~6 pt buckets — two DISTINCT beams are never <0.7 ft apart, so this
        # only ever collides for the same physical line.
        return (round((lx1 + lx2) / 2 / 6.0), round((ly1 + ly2) / 2 / 6.0))

    def _find_best_line(pcx, pcy, label_is_h, label_is_v,
                        enforce_dir, line_pool=None, claimed=None):
        _best = None
        _best_score = -1.0
        _best_mid = None
        for (lx1, ly1, lx2, ly2, ln) in (line_pool if line_pool is not None else all_lines):
            if claimed is not None:
                _mk = _mid_key(lx1, ly1, lx2, ly2)
                if _mk in claimed:
                    continue
            ldx = lx2 - lx1
            ldy = ly2 - ly1
            adx = abs(ldx)
            ady = abs(ldy)

            # Direction guard — label orientation must agree with line direction.
            if enforce_dir:
                if label_is_h and (ady > adx * 2):
                    continue
                if label_is_v and (adx > ady * 2):
                    continue

            # Per-direction max-length guard — reject grid/boundary lines
            if ady > adx * 2 and ln > MAX_V_MATCH:        # vertical line
                continue
            if adx > ady * 2 and ln > MAX_H_MATCH:        # horizontal line
                continue
            if not (adx > ady * 2) and not (ady > adx * 2):  # diagonal
                _diag_w = _mb_w if _mb_w < float("inf") else MAX_H_MATCH
                _diag_h = _mb_h if _mb_h < float("inf") else MAX_V_MATCH
                _max_diag = min(math.hypot(_diag_w, _diag_h) * 3.5,
                                math.hypot(_pb_w, _pb_h) * 0.85 if plan_bounds else MAX_LEN)
                if ln > _max_diag:
                    continue

            # Parametric projection onto line segment
            t = ((pcx - lx1) * ldx + (pcy - ly1) * ldy) / (ln * ln)
            # Allow ±45 % extension: raised from ±30 % so labels placed beyond
            # beam ends (common in congested areas and at cantilever tips) still
            # match their beam.  The proximity score naturally deprioritises
            # far-end labels when a closer line exists.
            if t < -0.45 or t > 1.45:
                continue
            t_c = max(0.0, min(1.0, t))
            px_proj = lx1 + t_c * ldx
            py_proj = ly1 + t_c * ldy
            dist = math.hypot(pcx - px_proj, pcy - py_proj)
            if dist >= LABEL_R:
                continue

            # Score = proximity × (0.97 + 0.03 × t_center) + length preference.
            #
            # Length preference (2026-07-20): a structural beam centreline is a
            # LONG drawn line; a dimension witness/extension tick is a SHORT
            # stub. On this project's framing plans the horizontal dimension
            # strings printed just above/below each girder row drop VERTICAL
            # witness ticks (~60 pt) that sit almost exactly on top of the
            # vertical beam centrelines — so a vertical label would score the
            # ~60 pt tick a hair higher than the real ~300 pt beam beside it
            # purely because the tick happened to be 2 pt closer, and the beam
            # got clipped to a 60 pt stub. (This only bites VERTICAL beams,
            # because only the horizontal dimension strings' witness lines run
            # vertically; horizontal beams were already correct, so this term
            # must not change their outcome.) Proximity still dominates
            # (weight 1.0); the length term is a small tie-breaker (max +0.06)
            # that only decides between two candidates the label sits almost
            # equally close to -- exactly the stub-vs-real-beam case. A real
            # beam is always the longer of the two, so this reliably prefers
            # it without widening any tolerance or matching new lines. Capped
            # by the per-direction max so it never rewards over-long
            # grid/boundary lines (those are already rejected above anyway).
            proximity  = 1.0 - dist / LABEL_R
            t_center   = 1.0 - 2.0 * abs(t_c - 0.5)
            _len_cap   = MAX_V_MATCH if (ady > adx * 2) else MAX_H_MATCH
            _len_pref  = 0.06 * min(ln / _len_cap, 1.0) if _len_cap > 0 else 0.0
            score = proximity * (0.97 + 0.03 * t_center) + _len_pref
            if score > _best_score:
                _best_score = score
                _best       = (lx1, ly1, lx2, ly2, ln)
                _best_mid   = _mid_key(lx1, ly1, lx2, ly2)
        return _best, _best_score, _best_mid

    def _match_profile(p, claimed):
        """Run all match passes for one profile against unclaimed lines."""
        pcx, pcy = p["cx"], p["cy"]
        lbw = p.get("bbox_w", 20.0)
        lbh = p.get("bbox_h",  8.0)
        label_is_h = lbw > lbh * 3.5
        label_is_v = lbh > lbw * 3.5
        b, s, m = _find_best_line(pcx, pcy, label_is_h, label_is_v, True, None, claimed)
        if not b:
            b, s, m = _find_best_line(pcx, pcy, label_is_h, label_is_v, False, None, claimed)
        if not b and thin_segs:
            _thin_long = [(x1, y1, x2, y2, ln) for (x1, y1, x2, y2, ln) in thin_segs
                          if ln >= MIN_LEN]
            if _thin_long:
                b, s, m = _find_best_line(pcx, pcy, label_is_h, label_is_v, True, _thin_long, claimed)
                if not b:
                    b, s, m = _find_best_line(pcx, pcy, label_is_h, label_is_v, False, _thin_long, claimed)
        return b, s, m

    # Pre-pass: each profile's independent best score → process closest-first so
    # the strongest (label-on-its-own-line) matches claim their line before
    # weaker ones, distributing labels across all lines instead of clustering.
    _keys = list(range(len(profiles))) if isinstance(profiles, list) else list(profiles.keys())
    _prelim = []
    for _pi in _keys:
        _, _sc, _ = _match_profile(profiles[_pi], None)
        _prelim.append((_sc, _pi))
    _order = [pi for _sc, pi in sorted(_prelim, key=lambda z: -z[0])]

    # ── Composite / built-up callouts ("W16x36" over "C12x20.7") ────────────
    # Two profile labels stacked almost directly on top of each other (same
    # text column, consecutive line spacing) are two LINES OF ONE CALLOUT for
    # a single physical beam (a wide-flange capped with a channel or plate),
    # not two separate beams. Under the normal one-line-per-label exclusivity
    # rule below, whichever label of the pair is processed second finds its
    # shared line already claimed and gets forced onto an unrelated line
    # elsewhere on the sheet -- producing a wrong-length / offset "beam" that
    # has nothing to do with the real member (the composite-callout overshoot
    # bug). Detect these stacked pairs up front so the second label simply
    # reuses the first's matched line instead of searching independently.
    # Require the pair to actually LOOK like a built-up callout (a primary
    # W/HSS shape paired with a channel/angle/plate cap) rather than just
    # "two labels that happen to sit close together" -- two independent,
    # genuinely separate beams can legitimately have their own labels a few
    # points apart in a dense area, and treating those as one would just move
    # the bug rather than fix it. This keeps the sharing rule narrow to the
    # one situation it's meant for.
    _CAP_RE = re.compile(r'^(?:C|L|MC|PL)\d')
    _PRIMARY_RE = re.compile(r'^(?:W|HSS)\d')
    _STACK_DX = 8.0    # same text column (allow narrow width drift)
    _STACK_DY = 16.0   # consecutive stacked text-line spacing (one line height)
    _stack_partner: dict = {}
    for _i in _keys:
        _pi = profiles[_i]
        _pi_prof = _pi.get("profile") or ""
        for _j in _keys:
            if _j <= _i:
                continue
            _pj = profiles[_j]
            _pj_prof = _pj.get("profile") or ""
            _is_cap_pair = ((_PRIMARY_RE.match(_pi_prof) and _CAP_RE.match(_pj_prof)) or
                            (_PRIMARY_RE.match(_pj_prof) and _CAP_RE.match(_pi_prof)))
            if (_is_cap_pair and
                    abs(_pi["cx"] - _pj["cx"]) <= _STACK_DX and
                    abs(_pi["cy"] - _pj["cy"]) <= _STACK_DY):
                _stack_partner.setdefault(_i, _j)
                _stack_partner.setdefault(_j, _i)

    _claimed_lines: set = set()
    for p_idx in _order:
        if p_idx in result:
            continue   # already filled in by its stacked-callout partner
        p = profiles[p_idx]
        pcx, pcy = p["cx"], p["cy"]
        best, _bscore, _bmid = _match_profile(p, _claimed_lines)
        if best:
            if _bmid is not None:
                _claimed_lines.add(_bmid)
            lx1, ly1, lx2, ly2, ln = best
            _init_dx = lx2 - lx1
            _init_dy = ly2 - ly1
            _init_ln = math.hypot(_init_dx, _init_dy)
            _ux = _init_dx / _init_ln if _init_ln > 0.1 else 1.0
            _uy = _init_dy / _init_ln if _init_ln > 0.1 else 0.0
            # ── Pass 0: collinear thick-segment chaining (COLUMN-GATED) ───────
            # Beams are frequently drawn as MULTIPLE short collinear segments —
            # CAD exporters break the centreline at every girder crossing.  The
            # label then matches only ONE short piece, so the rendered line is a
            # tiny stub instead of the full span (the bug being fixed here).
            #
            # Recover the full length by chaining every REAL drawn segment that
            # is collinear with the matched one (same direction within 4°, same
            # infinite line within ~5 pt).  This follows only ACTUAL drawn
            # geometry, so it can never extend into empty space.
            #
            # CRITICAL GUARD — column gating: two DIFFERENT beams that meet at a
            # column are also collinear, so naive chaining bridges them into one
            # cross-bay line (the over-extension regression).  A real single beam
            # is only ever broken at GIRDER crossings (mid-span), never at a
            # column.  So after chaining we truncate any extension that ran PAST
            # a column back TO that column: a column between the matched piece
            # and the chained end means we crossed into a neighbouring beam.
            _om_x1, _om_y1, _om_x2, _om_y2 = lx1, ly1, lx2, ly2   # original extent
            _is_heavy_girder = bool(re.match(r'^(?:W3[0-9]|W4[0-9]|W27X[1-9])', (p.get("profile") or "")))
            _chain_gap_tol = (max(35.0, pts_per_foot * 14.0) if pts_per_foot > 0 else 120.0) if _is_heavy_girder else 4.0
            _c1, _c2, _c3, _c4, _cln = _extend_with_thin_segs(
                lx1, ly1, lx2, ly2, all_lines,
                gap_tol=_chain_gap_tol)
            _cadx, _cady = abs(_c3 - _c1), abs(_c4 - _c2)
            _is_h_chain = _cadx > _cady
            _ccap = MAX_H_MATCH if _is_h_chain else MAX_V_MATCH
            if _cln <= _ccap and (_cln > ln + 1):
                # ── Joist-pattern guard ────────────────────────────────────
                # Before accepting the chained result, check if the collinear
                # segments form a JOIST PATTERN (many short segments with
                # regular gaps).  Real beams are broken at 1-3 girder crossings
                # with large gaps; joists have ≥4 densely-packed breaks.
                # If detected, skip the chain — the original matched segment
                # length is kept (short stub for a joist mark, not a full beam).
                if _is_joist_pattern(
                        _c1, _c2, _c3, _c4, all_lines,
                        gap_tol=_chain_gap_tol):
                    # Treat as joist: skip chaining, keep original segment only.
                    # The resulting short stub will fail _span_valid unless it
                    # happens to match a real beam line, so it gets dropped.
                    pass
                else:
                    # Gate on REAL column symbols only — NOT grid lines.  A grid line
                    # crossing does not mean a column exists at THIS beam's position
                    # (a vertical infill beam crosses many row grid lines but frames
                    # girder-to-girder with no column between).  Truncate only where
                    # an actual detected column sits ON the beam axis between the
                    # matched piece and the chained end — that is a real beam-to-beam
                    # junction (two members meeting at a column), not one beam.
                    _PERP = 22.0   # column centre must lie within this of the axis
                    if _is_h_chain:
                        _yl = (_c2 + _c4) / 2.0
                        _ol, _orr = min(_om_x1, _om_x2), max(_om_x1, _om_x2)
                        _nl, _nr  = min(_c1, _c3),       max(_c1, _c3)
                        _colx = [s["cx"] for s in (column_symbols or [])
                                 if abs(s["cy"] - _yl) < _PERP]
                        _lc = [c for c in _colx if _nl < c < _ol - 2]
                        if _lc:
                            _nl = max(_lc)         # stop at column nearest matched piece
                        _rc = [c for c in _colx if _orr + 2 < c < _nr]
                        if _rc:
                            _nr = min(_rc)
                        if abs(_ux) > 1e-6:
                            ly1 = _om_y1 + (_nl - _om_x1) * (_uy / _ux)
                            ly2 = _om_y1 + (_nr - _om_x1) * (_uy / _ux)
                        else:
                            ly1 = _yl
                            ly2 = _yl
                        lx1, lx2 = _nl, _nr
                        ln = math.hypot(lx2 - lx1, ly2 - ly1)
                    else:
                        _xl = (_c1 + _c3) / 2.0
                        _ot, _ob = min(_om_y1, _om_y2), max(_om_y1, _om_y2)
                        _nt, _nb = min(_c2, _c4),       max(_c2, _c4)
                        _coly = [s["cy"] for s in (column_symbols or [])
                                 if abs(s["cx"] - _xl) < _PERP]
                        _tc = [c for c in _coly if _nt < c < _ot - 2]
                        if _tc:
                            _nt = max(_tc)
                        _bc = [c for c in _coly if _ob + 2 < c < _nb]
                        if _bc:
                            _nb = min(_bc)
                        if abs(_uy) > 1e-6:
                            lx1 = _om_x1 + (_nt - _om_y1) * (_ux / _uy)
                            lx2 = _om_x1 + (_nb - _om_y1) * (_ux / _uy)
                        else:
                            lx1 = _xl
                            lx2 = _xl
                        ly1, ly2 = _nt, _nb
                        ln = math.hypot(lx2 - lx1, ly2 - ly1)
            # Remember the matched centreline extent (AFTER collinear chaining)
            # BEFORE the snap passes.  The final clamp below bounds the COMBINED
            # growth of the snap passes (column snap, intersection snap) to
            # _EXT_MAX past this extent, so a beam can never be inflated far past
            # its real drawn line — this stops hairline grid/border segments from
            # being chained into huge cross-the-sheet "beams" on dense drawings.
            _draw_x1, _draw_y1 = lx1, ly1
            _draw_x2, _draw_y2 = lx2, ly2
            # ── Pass 1: hairline stubs at column connection zones ─────────────
            # The beam centreline transitions to a thin stroke (<0.3 pt) inside
            # the column zone.  Extend using those saved thin_segs.
            if thin_segs:
                lx1, ly1, lx2, ly2, ln = _extend_with_thin_segs(
                    lx1, ly1, lx2, ly2, thin_segs)
            # ── Pass 3a: column-symbol snap ───────────────────────────────────
            # Snap endpoints to the nearest real column lying along the beam
            # axis.  Targets = detected I/H column symbols PLUS grid-line
            # intersections (also exact column centres).  Both are guaranteed
            # column positions, so this can connect a short-drawn beam to its
            # column without any risk of flying into empty space.
            _col_targets = list(column_symbols or [])
            if v_grid and h_grid:
                _col_targets += [{"cx": gx, "cy": gy}
                                 for gx in v_grid for gy in h_grid]
            if _col_targets:
                lx1, ly1, lx2, ly2, ln = _snap_to_columns_along_axis(
                    lx1, ly1, lx2, ly2, _col_targets)
            # ── Pass 3b: physical intersection snap ───────────────────────────────
            # Geometrically extend each beam endpoint by up to _EXT_MAX points
            # to the nearest crossing line, so beams meet at the column/beam
            # centreline rather than stopping at the column face.
            #
            # Works for H, V AND diagonal (D) beams — critical for rotated-grid
            # drawings where all structural beams are at 30-45° angles.
            #
            # Algorithm: for each endpoint, project the beam direction forward/
            # backward by up to _EXT_MAX, find the nearest line segment that
            # actually intersects that extension, and snap to the intersection.
            # EXT_MAX: how far each endpoint can be extended to reach a column/beam.
            # Scale with drawing — gap from beam-end to column CL is typically
            # 6–12 inches (half column flange) + any drafter shortfall, ≈ 2–8 ft.
            # Formula: 8 ft × pts_per_foot; clamp 40–150 pt for unknown scales.
            # 15 ft allows reaching the column CL even when only a short stub
            # of the beam is drawn (some drafters draw to column face, or split
            # beams into bay-by-bay segments).  Nearest-snap stops at the first
            # real crossing line so there is no overrun.
            # Beam-face → column-centreline gap is only half a column depth
            # (< 1 ft).  Allow 2.5 ft of extension to bridge that plus minor
            # drafter slack.  Crucially, when NO column line is within this
            # range the endpoint KEEPS its drawn position instead of flying out
            # to a far grid/perimeter line in empty space (the overshoot bug).
            _EXT_MAX = max(25, min(65, pts_per_foot * 3.5)) if pts_per_foot > 0 else 35.0
            _adx, _ady = abs(lx2 - lx1), abs(ly2 - ly1)
            _is_H = _adx > _ady * 2
            _is_V = _ady > _adx * 2

            # ── General line-segment intersection helper ──────────────────────
            def _seg_intersect_t(ax1, ay1, adx, ady, bx1, by1, bx2, by2):
                """
                Return t along beam ray (ax1+t*adx, ay1+t*ady) where it
                intersects segment B, or None if no intersection.
                t < 0  = behind endpoint, 0 = at endpoint, t > 0 = ahead.
                Only returns when the intersection is within segment B (u ∈ [0,1]).
                """
                bdx = bx2 - bx1
                bdy = by2 - by1
                denom = adx * bdy - ady * bdx
                if abs(denom) < 1e-9:
                    return None
                t = ((bx1 - ax1) * bdy - (by1 - ay1) * bdx) / denom
                u = ((bx1 - ax1) * ady - (by1 - ay1) * adx) / denom
                if -0.05 <= u <= 1.05:
                    return t
                return None

            # ── Pre-filter candidate lines ────────────────────────────────────
            # Only lines long enough to be a real structural element (column
            # web/flange or girder) qualify as snap targets.  Short ticks,
            # dimension arrows, and hatch marks are excluded so the nearest-snap
            # doesn't stop at a 5 pt annotation and leave the beam 60 pt short
            # of the actual column.
            # Minimum: 5 ft equivalent at the drawing scale, floor 30 pt.
            # 5 ft filters out dimension ticks, hatch lines, and connection
            # detail marks while keeping all real column and girder lines.
            _SNAP_MIN = max(30, pts_per_foot * 5) if pts_per_foot > 0 else 30

            if _is_H:
                _cand_lines = [(px1, py1, px2, py2)
                               for (px1, py1, px2, py2, pln) in all_lines
                               if abs(py2 - py1) > abs(px2 - px1) * 2
                               and pln >= _SNAP_MIN]
                # Also include thin crossing lines (hairline column/girder strokes)
                _cand_lines += [(px1, py1, px2, py2)
                                for (px1, py1, px2, py2, pln) in thin_segs
                                if abs(py2 - py1) > abs(px2 - px1) * 2
                                and pln >= _SNAP_MIN]
            elif _is_V:
                _cand_lines = [(px1, py1, px2, py2)
                               for (px1, py1, px2, py2, pln) in all_lines
                               if abs(px2 - px1) > abs(py2 - py1) * 2
                               and pln >= _SNAP_MIN]
                # Also include thin crossing lines (hairline column/girder strokes)
                _cand_lines += [(px1, py1, px2, py2)
                                for (px1, py1, px2, py2, pln) in thin_segs
                                if abs(px2 - px1) > abs(py2 - py1) * 2
                                and pln >= _SNAP_MIN]
            else:
                # Diagonal beam — collect lines NOT parallel to it
                # (angle difference > 20°  ≈  dot product < cos20 = 0.94)
                _blen = math.hypot(lx2 - lx1, ly2 - ly1)
                _bnx  = (lx2 - lx1) / _blen if _blen > 0 else 1.0
                _bny  = (ly2 - ly1) / _blen if _blen > 0 else 0.0
                _cand_lines = []
                for (px1, py1, px2, py2, pln) in all_lines + thin_segs:
                    if pln < _SNAP_MIN:
                        continue
                    _pnx = (px2 - px1) / pln
                    _pny = (py2 - py1) / pln
                    _dot = abs(_bnx * _pnx + _bny * _pny)
                    if _dot < 0.94:  # not parallel
                        _cand_lines.append((px1, py1, px2, py2))

            # ── Extend endpoint A (the "start" end of the beam) ──────────────
            # Direction from A outward = -(lx2-lx1, ly2-ly1) direction
            _blen = math.hypot(lx2 - lx1, ly2 - ly1) or 1.0
            _fwdx = (lx2 - lx1) / _blen   # forward unit vector
            _fwdy = (ly2 - ly1) / _blen
            _best_t_A = float("inf")   # take NEAREST crossing line, not furthest
            _snap_A = None
            for (px1, py1, px2, py2) in _cand_lines:
                # Shoot ray backward from lx1,ly1
                t = _seg_intersect_t(lx1, ly1, -_fwdx, -_fwdy,
                                     px1, py1, px2, py2)
                if t is not None and 0.0 < t <= _EXT_MAX:
                    if t < _best_t_A:
                        _best_t_A = t
                        _snap_A = (lx1 - _fwdx * t, ly1 - _fwdy * t)
            if _snap_A:
                lx1, ly1 = _snap_A

            # ── Extend endpoint B (the "end" end of the beam) ────────────────
            _best_t_B = float("inf")   # take NEAREST crossing line, not furthest
            _snap_B = None
            for (px1, py1, px2, py2) in _cand_lines:
                # Shoot ray forward from lx2,ly2
                t = _seg_intersect_t(lx2, ly2, _fwdx, _fwdy,
                                     px1, py1, px2, py2)
                if t is not None and 0.0 < t <= _EXT_MAX:
                    if t < _best_t_B:
                        _best_t_B = t
                        _snap_B = (lx2 + _fwdx * t, ly2 + _fwdy * t)
            if _snap_B:
                lx2, ly2 = _snap_B

            # ── Pass 3d: column-centreline snap ───────────────────────────────
            # Grid lines ARE the column centrelines.  A drawn beam stops at the
            # column FACE — ~1–2 ft short of the centre.  Snap each endpoint to
            # the NEAREST grid line, but only within _EXT_MAX (so it reaches the
            # adjacent column centre and never jumps to the next bay, and never
            # overshoots — nearest-snap pulls an over-long end back too).
            # This is what makes beams land true centre-to-centre, generically.
            _curr_dx = lx2 - lx1
            _curr_dy = ly2 - ly1
            _curr_ln = math.hypot(_curr_dx, _curr_dy)
            if _curr_ln > 0.1:
                _ux, _uy = _curr_dx / _curr_ln, _curr_dy / _curr_ln
            else:
                _ux, _uy = 1.0, 0.0

            if _is_H and _col_snap_x:
                _gx1 = min(_col_snap_x, key=lambda gx: abs(lx1 - gx))
                _gx2 = min(_col_snap_x, key=lambda gx: abs(lx2 - gx))
                # Only snap when the two ends reach DIFFERENT columns — never
                # collapse both ends onto one column (which would erase the
                # beam) and never lose the span of a short in-bay beam.
                if abs(_gx1 - _gx2) > 5:
                    if abs(lx1 - _gx1) <= _EXT_MAX:
                        if abs(_ux) > 1e-6:
                            ly1 = ly1 + (_gx1 - lx1) * (_uy / _ux)
                        lx1 = _gx1
                    if abs(lx2 - _gx2) <= _EXT_MAX:
                        if abs(_ux) > 1e-6:
                            ly2 = ly2 + (_gx2 - lx2) * (_uy / _ux)
                        lx2 = _gx2
            elif _is_V and _col_snap_y:
                _gy1 = min(_col_snap_y, key=lambda gy: abs(ly1 - gy))
                _gy2 = min(_col_snap_y, key=lambda gy: abs(ly2 - gy))
                if abs(_gy1 - _gy2) > 5:
                    if abs(ly1 - _gy1) <= _EXT_MAX:
                        if abs(_uy) > 1e-6:
                            lx1 = lx1 + (_gy1 - ly1) * (_ux / _uy)
                        ly1 = _gy1
                    if abs(ly2 - _gy2) <= _EXT_MAX:
                        if abs(_uy) > 1e-6:
                            lx2 = lx2 + (_gy2 - ly2) * (_ux / _uy)
                        ly2 = _gy2

            # ── FINAL ANTI-OVERSHOOT CLAMP ────────────────────────────────────
            # No endpoint may sit more than _EXT_MAX beyond the true drawn extent
            # captured above.  This bounds the COMBINED effect of every snap pass
            # (column-symbol snap, intersection snap), so a beam can never fly
            # past its drawn line into empty space — on any drawing, generically.
            # Measured along the original drawn axis; movement back toward the
            # beam (shrinking) is never clamped.
            _odx = _draw_x2 - _draw_x1
            _ody = _draw_y2 - _draw_y1
            _oln = math.hypot(_odx, _ody)
            if _oln > 1.0:
                _oux, _ouy = _odx / _oln, _ody / _oln
                # Endpoint A: outward direction is -axis; clamp extension to _EXT_MAX
                _extA = -((lx1 - _draw_x1) * _oux + (ly1 - _draw_y1) * _ouy)
                if _extA > _EXT_MAX:
                    lx1 = _draw_x1 - _oux * _EXT_MAX
                    ly1 = _draw_y1 - _ouy * _EXT_MAX
                # Endpoint B: outward direction is +axis
                _extB = (lx2 - _draw_x2) * _oux + (ly2 - _draw_y2) * _ouy
                if _extB > _EXT_MAX:
                    lx2 = _draw_x2 + _oux * _EXT_MAX
                    ly2 = _draw_y2 + _ouy * _EXT_MAX

            ln = math.hypot(lx2 - lx1, ly2 - ly1)
            adx = abs(lx2 - lx1)
            ady = abs(ly2 - ly1)
            if adx > ady * 2:
                bdir = "H"
            elif ady > adx * 2:
                bdir = "V"
            else:
                bdir = "D"   # diagonal beam
            result[p_idx] = {
                "x1": lx1, "y1": ly1,
                "x2": lx2, "y2": ly2,
                "dir":       bdir,
                "length_pt": ln,
            }
            # Share this same beam with a stacked-callout partner (e.g. the
            # "C12x20.7" line of a "W16x36 / C12x20.7" pair) instead of
            # letting it search separately and get pushed onto a wrong line.
            _partner = _stack_partner.get(p_idx)
            if _partner is not None and _partner not in result:
                result[_partner] = dict(result[p_idx])

    matched = len(result)
    print(f"[BEAM_LINES] {matched}/{len(profiles)} profiles matched "
          f"to drawn beam lines")
    return result, all_lines


def detect_beam_directions(page, profiles: list, plan_bounds: tuple) -> dict:
    """
    Determine whether each beam profile label lies on a horizontal or vertical
    structural member by finding the nearest significant vector line segment.

    Strategy
    --------
    • Collect all line segments from page vector drawings that are:
        – Inside the plan boundary
        – Between MIN_LEN and MAX_LEN pts long (ignores ticks and grid lines)
        – Clearly horizontal (dx/dy > 2) or vertical (dy/dx > 2)
    • For each profile, whichever orientation class has a member closer than
      SEARCH_R pts wins.  Ties (or nothing within range) default to "H".

    Returns
    -------
    dict  profile_idx → "H" | "V"
    """
    bx0, by0, bx1, by1 = plan_bounds

    MIN_LEN  = 40    # ignore ticks, hatching, and annotation lines
    MAX_LEN  = 600   # ignore full-width grid lines and sheet border
    DIR_RATIO = 2.0  # dx/dy (or dy/dx) must exceed this to be "clearly" H or V
    SEARCH_R  = 60   # max distance from label to candidate line midpoint

    h_lines: list[tuple[float, float]] = []
    v_lines: list[tuple[float, float]] = []
    # Lines that are neither clearly H nor clearly V — a genuinely skewed/
    # angled beam (e.g. in a rotated wing of the building). Previously these
    # were dropped entirely, so a profile label sitting on a true diagonal
    # beam had no candidate line in range and silently defaulted to "H",
    # which downstream gets snapped onto the horizontal grid and rendered as
    # a straight line — visibly wrong against the angled drawing underneath.
    d_lines: list[tuple[float, float, float]] = []  # (lx, ly, angle_deg)

    try:
        for d in page.get_drawings():
            for item in d.get("items", []):
                if item[0] != "l":
                    continue
                try:
                    p1, p2 = item[1], item[2]
                    dx = abs(p2.x - p1.x)
                    dy = abs(p2.y - p1.y)
                    ln = math.hypot(dx, dy)
                    if ln < MIN_LEN or ln > MAX_LEN:
                        continue
                    lx = (p1.x + p2.x) / 2
                    ly = (p1.y + p2.y) / 2
                    if not (bx0 <= lx <= bx1 and by0 <= ly <= by1):
                        continue
                    if dx > dy * DIR_RATIO:
                        h_lines.append((lx, ly))
                    elif dy > dx * DIR_RATIO:
                        v_lines.append((lx, ly))
                    else:
                        angle = math.degrees(math.atan2(p2.y - p1.y, p2.x - p1.x))
                        d_lines.append((lx, ly, angle))
                except Exception:
                    continue
    except Exception:
        pass

    print(f"[BEAM_DIR] H-lines: {len(h_lines)}  V-lines: {len(v_lines)}  D-lines: {len(d_lines)}")

    directions: dict[int, str] = {}
    angles: dict[int, float] = {}
    for p_idx, p in enumerate(profiles):
        pcx, pcy = p["cx"], p["cy"]
        d_h = min((math.hypot(pcx - lx, pcy - ly) for lx, ly in h_lines),
                  default=float("inf"))
        d_v = min((math.hypot(pcx - lx, pcy - ly) for lx, ly in v_lines),
                  default=float("inf"))
        nearest_d = min(d_lines, key=lambda t: math.hypot(pcx - t[0], pcy - t[1]), default=None)
        d_d = math.hypot(pcx - nearest_d[0], pcy - nearest_d[1]) if nearest_d else float("inf")

        best = min(d_h, d_v, d_d)
        if best <= SEARCH_R:
            if best == d_d:
                directions[p_idx] = "D"
                angles[p_idx] = nearest_d[2]
            else:
                directions[p_idx] = "H" if d_h <= d_v else "V"
        else:
            directions[p_idx] = "H"  # default — horizontal beam, no line found at all

    return directions


# ── Profile helpers ───────────────────────────────────────────────────────────
def normalize_profile(text: str) -> str:
    t = text.upper().strip()
    t = re.sub(r'[^A-Z0-9X/]', '', t)
    t = re.sub(r'^VV', "W", t)
    t = re.sub(r'^V(?=\d)', "W", t)
    t = t.rstrip('/')  # strip trailing slash OCR artifact (e.g. "HSS6X6X3/8/")
    return t


_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.gif', '.webp'}


def _pytesseract_to_dict(data: dict, page_w: float, page_h: float,
                         pix_w: int, pix_h: int) -> dict:
    """Convert pytesseract image_to_data output to a fitz-compatible text dict."""
    sx = page_w / max(pix_w, 1)
    sy = page_h / max(pix_h, 1)
    blocks = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        try:
            conf = int(data["conf"][i])
        except (ValueError, TypeError):
            conf = 0
        if conf < 30:        # skip very low-confidence words
            continue
        lx = data["left"][i]  * sx
        ty = data["top"][i]   * sy
        rx = (data["left"][i] + data["width"][i])  * sx
        by = (data["top"][i]  + data["height"][i]) * sy
        h  = max(by - ty, 1)
        blocks.append({
            "type": 0,
            "bbox": (lx, ty, rx, by),
            "lines": [{
                "bbox": (lx, ty, rx, by),
                "spans": [{"text": text, "bbox": (lx, ty, rx, by),
                            "size": h * 0.75}],
            }],
        })
    return {"blocks": blocks}


_easyocr_reader = None   # lazy-loaded singleton

def _get_easyocr_reader():
    """Return a cached EasyOCR reader (loaded once per process)."""
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            print("[OCR] Loading EasyOCR model (first-run download may take a moment)...")
            _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            print("[OCR] EasyOCR ready")
        except Exception as e:
            print(f"[OCR] EasyOCR load failed: {e}")
    return _easyocr_reader


def _easyocr_to_dict(results: list, page_w: float, page_h: float,
                     pix_w: int, pix_h: int) -> dict:
    """
    Convert EasyOCR result list to fitz-compatible text dict.

    Each item in results may be a 3-tuple (bbox_pts, text, conf) or a
    4-tuple (bbox_pts, text, conf, rot_pass) where rot_pass is:
      0 = original orientation (horizontal text)
      1 = 90° CCW rotation (reads CW-rotated vertical text in original)
      2 = 90° CW rotation  (reads CCW-rotated vertical text in original)

    rot_pass is stored in each span so that extract_profiles can use it
    to infer beam direction for raster images (pass 1/2 → vertical member).

    All coordinates are in PIXEL space of the rendered image; we scale to
    fitz page-point space.
    """
    sx = page_w / max(pix_w, 1)
    sy = page_h / max(pix_h, 1)
    blocks = []
    for item in results:
        if len(item) == 4:
            bbox_pts, text, conf, rot_pass = item
        else:
            bbox_pts, text, conf = item
            rot_pass = 0
        text = text.strip()
        if not text or conf < 0.20:          # lowered from 0.25 for better recall
            continue
        xs = [p[0] for p in bbox_pts]
        ys = [p[1] for p in bbox_pts]
        lx = min(xs) * sx;  rx = max(xs) * sx
        ty = min(ys) * sy;  by = max(ys) * sy
        h  = max(by - ty, 1)
        blocks.append({
            "type": 0,
            "bbox": (lx, ty, rx, by),
            "lines": [{
                "bbox": (lx, ty, rx, by),
                "spans": [{"text": text, "bbox": (lx, ty, rx, by),
                            "size": h * 0.75,
                            "rot_pass": rot_pass}],
            }],
        })
    return {"blocks": blocks}


def _get_text_dict(page, page_w: float = None, page_h: float = None
                   ) -> tuple[dict, bool]:
    """
    Return (text_dict, is_raster) for a fitz page.

    Attempt order
    ─────────────
    1. Embedded vector text (zero cost, always correct for proper PDFs)
    2. EasyOCR (pure-Python, no Tesseract required, good on engineering drawings)
    3. PyMuPDF built-in OCR  — requires Tesseract + tessdata
    4. pytesseract           — requires pytesseract + Tesseract binary

    Returns is_raster=False when embedded text was sufficient, True otherwise.
    """
    # ── 1. Embedded text ─────────────────────────────────────────────────────
    td = page.get_text("dict")
    n_chars = sum(len(sp["text"].strip())
                  for bl in td.get("blocks", [])
                  for ln in bl.get("lines", [])
                  for sp in ln.get("spans", []))
    if n_chars >= 20:
        return td, False

    print(f"[OCR] Embedded text chars={n_chars} — activating OCR")

    pw = page_w or page.rect.width
    ph = page_h or page.rect.height

    # ── 2. EasyOCR — 3-pass (0°, 90° CCW, 90° CW) + preprocessing ──────────────
    #
    # Structural drawings place beam labels PARALLEL to the member axis so
    # vertical member labels are rotated 90° in the image.  A single forward
    # pass only reads horizontal text; we rotate the image and transform
    # coordinates back to catch vertical text as well.
    #
    # Each result is stored as a 4-tuple (bbox, text, conf, rot_pass) where
    # rot_pass encodes which orientation found the text:
    #   0 = original  →  horizontal member label  (dir_hint = H)
    #   1 = 90° CCW   →  CW-rotated label in original  (dir_hint = V)
    #   2 = 90° CW    →  CCW-rotated label in original (dir_hint = V)
    #
    # Preprocessing: convert to greyscale, boost contrast, sharpen.
    # This significantly improves OCR accuracy on dense engineering drawings
    # with thin lines, small text, and low ink-to-paper contrast.
    reader = _get_easyocr_reader()
    if reader is not None:
        try:
            pix     = page.get_pixmap(dpi=300)        # was 200 — higher res for small text
            pil_img = PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # CLAHE preprocessing: adaptive local contrast enhancement.
            # Better than global contrast because it improves dark/faded regions
            # without over-saturating bright ones, keeping thin strokes like
            # "/" in HSS profiles (e.g. HSS6X6X3/8) readable.
            try:
                import cv2 as _cv2
                _gray = np.array(pil_img.convert("L"))
                # Step 1: CLAHE for local contrast (handles uneven ink/scan)
                _clahe = _cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                _enhanced = _clahe.apply(_gray)
                # Step 2: Unsharp mask to sharpen blurry scanned text.
                # Scanned drawings often have low-frequency blur from the scanner
                # optics; sharpening recovers thin strokes like "/" in "HSS6X6X3/8".
                _blur    = _cv2.GaussianBlur(_enhanced, (0, 0), sigmaX=1.5)
                _sharp   = _cv2.addWeighted(_enhanced, 1.5, _blur, -0.5, 0)
                pil_img = PILImage.fromarray(
                    _cv2.cvtColor(_sharp, _cv2.COLOR_GRAY2RGB))
            except Exception:
                # Fallback: mild global contrast if cv2 unavailable
                pil_img = PILImage.fromarray(
                    np.stack([np.array(ImageEnhance.Contrast(
                        pil_img.convert("L")).enhance(1.4))] * 3, axis=-1))

            img_arr = np.array(pil_img)
            H_pix, W_pix = img_arr.shape[:2]

            # Characters found in structural steel section labels + grid bubbles
            _ALLOW = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./-×X"

            # EasyOCR parameters tuned for engineering drawings.
            # We intentionally keep link_threshold at the default (0.4) to
            # prevent characters from different nearby labels being merged
            # into one span (e.g. "W12X26" + adjacent "1" → "W12X261").
            # text_threshold lowered slightly to catch low-ink labels.
            _OCR_KW = dict(
                detail=1, allowlist=_ALLOW, paragraph=False,
                text_threshold=0.65,   # default 0.7 — slightly more detections
                low_text=0.35,         # default 0.4 — catch edge characters
                link_threshold=0.4,    # default 0.4 — keep to avoid cross-label merging
                contrast_ths=0.1,
                adjust_contrast=0.5,
            )

            # Pass 0 — 0°: horizontal text (most beam labels, grid numbers)
            res = [(bbox, text, conf, 0)
                   for (bbox, text, conf) in reader.readtext(img_arr, **_OCR_KW)]

            # Pass 1 — 90° CCW: reads labels rotated 90° CW in the original.
            #   rot90 CCW transform: orig(x,y) → rot(x_r=y, y_r=W-1-x)
            #   Inverse: rot(x_r,y_r) → orig(x=W-1-y_r, y=x_r)
            img_rot = np.rot90(img_arr, k=1)
            for (bbox, text, conf) in reader.readtext(img_rot, **_OCR_KW):
                orig_bbox = [[W_pix - 1 - float(py), float(px)]
                             for (px, py) in bbox]
                res.append((orig_bbox, text, conf, 1))

            # Pass 2 — 90° CW: reads labels rotated 90° CCW in the original.
            #   rot90 CW (=rot270 CCW): orig(x,y) → rot(x_r=H-1-y, y_r=x)
            #   Inverse: rot(x_r,y_r) → orig(x=y_r, y=H-1-x_r)
            img_rot3 = np.rot90(img_arr, k=3)
            for (bbox, text, conf) in reader.readtext(img_rot3, **_OCR_KW):
                orig_bbox = [[float(py), H_pix - 1 - float(px)]
                             for (px, py) in bbox]
                res.append((orig_bbox, text, conf, 2))

            td2 = _easyocr_to_dict(res, pw, ph, W_pix, H_pix)
            n2  = sum(len(sp["text"].strip())
                      for bl in td2.get("blocks", [])
                      for ln in bl.get("lines", [])
                      for sp in ln.get("spans", []))
            if n2 >= 10:
                print(f"[OCR] EasyOCR 3-pass: {n2} chars / {len(res)} regions  "
                      f"(pass0={sum(1 for r in res if r[3]==0)}  "
                      f"pass1={sum(1 for r in res if r[3]==1)}  "
                      f"pass2={sum(1 for r in res if r[3]==2)})")
                return td2, True
        except Exception as e:
            print(f"[OCR] EasyOCR inference failed: {e}")

    # ── 3. PyMuPDF built-in OCR (Tesseract) ──────────────────────────────────
    try:
        tp  = page.get_textpage_ocr(flags=0, language="eng", dpi=300, full=True)
        td3 = page.get_text("dict", textpage=tp)
        n3  = sum(len(sp["text"].strip())
                  for bl in td3.get("blocks", [])
                  for ln in bl.get("lines", [])
                  for sp in ln.get("spans", []))
        if n3 >= 10:
            print(f"[OCR] PyMuPDF/Tesseract: {n3} chars extracted")
            return td3, True
    except Exception as e:
        print(f"[OCR] PyMuPDF OCR: {e}")

    # ── 4. pytesseract ────────────────────────────────────────────────────────
    try:
        import pytesseract as _pyt
        pix     = page.get_pixmap(dpi=200)
        pil_img = PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
        data    = _pyt.image_to_data(pil_img, output_type=_pyt.Output.DICT,
                                     lang="eng", config="--psm 11")
        td4  = _pytesseract_to_dict(data, pw, ph, pix.width, pix.height)
        n4   = sum(len(sp["text"].strip())
                   for bl in td4.get("blocks", [])
                   for ln in bl.get("lines", [])
                   for sp in ln.get("spans", []))
        if n4 >= 10:
            print(f"[OCR] pytesseract: {n4} chars extracted")
            return td4, True
    except Exception as e:
        print(f"[OCR] pytesseract: {e}")

    print("[OCR] All OCR methods failed for this raster image.")
    return {"blocks": []}, True


# ── Plan boundary (from grid bubble positions) ────────────────────────────────
def find_plan_boundary(page, page_w, page_h, text_dict=None):
    """
    Derive the structural plan extent from grid bubble positions.

    Grid bubbles (letter labels A/B/C… AND number labels 1/2/3…) always appear
    AROUND the perimeter of the structural plan.  Their collective bounding box
    plus a small buffer gives a reliable plan boundary regardless of drawing
    orientation.

    This handles BOTH common layouts transparently:
      • Letters at top/bottom, numbers at left/right   (e.g. "Structural snaps")
      • Letters at left/right, numbers at top/bottom   (e.g. Calsteel drawings)
      • Any mixed layout

    Why NOT separate letter_xs / number_ys (old approach):
      In a "letters-on-left" drawing all letter X values cluster near the left
      edge, so letter_xs gives a ~0-width X range — the plan boundary collapses
      to a sliver and nothing is extracted.

    Gap detection (Y axis):
      If the sorted Y positions of all grid labels have a gap > 12% of page
      height we drop everything below that gap.  Such a gap signals the end of
      the structural plan and the start of the notes / title block area.
    """
    all_xs: list[float] = []
    all_ys: list[float] = []

    _td = text_dict if text_dict is not None else page.get_text("dict")
    for block in _td["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t  = span["text"].strip()
                fs = span.get("size", 10)
                if not t or len(t) > 5 or fs < 6:
                    continue
                cx = (span["bbox"][0] + span["bbox"][2]) / 2
                cy = (span["bbox"][1] + span["bbox"][3]) / 2

                if _GRID_LETTER.match(t):
                    all_xs.append(cx)
                    all_ys.append(cy)
                elif _GRID_NUMBER.match(t):
                    try:
                        n = float(t)
                        # Accept grid numbers 0.5–500.  Upper bound was 25 which
                        # silently dropped columns numbered 26+ (e.g. a drawing
                        # spanning grids 21–34 lost its entire right half).
                        # 500 covers any practical building grid while still
                        # excluding large dimension/load annotation numbers.
                        if 0.5 <= n <= 500:
                            all_xs.append(cx)
                            all_ys.append(cy)
                    except ValueError:
                        pass

    # ── Gap detection on Y: drop labels below the first large vertical gap ─────
    # Large gap  ≡  notes / title block is separated from the structural plan.
    # Threshold raised to 20% so that widely-spaced bottom grid rows (e.g. A.7→A)
    # are NOT incorrectly trimmed — those rows still contain real structural members.
    if len(all_ys) >= 3:
        sorted_ys = sorted(all_ys)
        best_gap   = 0.0
        gap_cutoff = sorted_ys[-1]           # default: keep everything
        for i in range(len(sorted_ys) - 1):
            g = sorted_ys[i + 1] - sorted_ys[i]
            if g > best_gap:
                best_gap   = g
                gap_cutoff = sorted_ys[i]    # last Y before the gap
        if best_gap > page_h * 0.28:         # was 0.12 — raised; only fires for very obvious title-block separation
            old_max = max(all_ys)
            all_xs = [all_xs[i] for i, y in enumerate(all_ys) if y <= gap_cutoff]
            all_ys = [y           for y in all_ys               if y <= gap_cutoff]
            if all_ys:
                print(f"[BOUNDARY] gap={best_gap:.0f}pt — trimmed Y max "
                      f"from {old_max:.0f} to {max(all_ys):.0f}")

    if len(all_xs) >= 2 and len(all_ys) >= 2:
        # 300 pt buffer: raised from 150 so beams and labels at the outermost
        # column strip (which sits well beyond the last grid bubble) are included.
        # This is the universal fix for drawings where plan_bounds was clipping
        # the right / bottom edge of the framing area.
        buf = 300
        b = (
            max(0,      min(all_xs) - buf),
            max(0,      min(all_ys) - buf),
            min(page_w, max(all_xs) + buf),
            min(page_h, max(all_ys) + buf),
        )
        print(f"[BOUNDARY] grid-derived x=[{b[0]:.0f},{b[2]:.0f}] "
              f"y=[{b[1]:.0f},{b[3]:.0f}]")
        return b

    print("[BOUNDARY] fallback margins")
    return (page_w * 0.03, page_h * 0.02, page_w * 0.97, page_h * 0.98)


def refine_column_geometry(drawings, cluster_idx, scale_ratio):
    lines = []
    has_rect = False
    has_circle = False
    rect_dims = []
    
    for idx in cluster_idx:
        d = drawings[idx]
        items = d.get("items", [])
        for item in items:
            kind = item[0]
            if kind == "l":
                p1, p2 = item[1], item[2]
                lines.append((p1.x, p1.y, p2.x, p2.y))
            elif kind == "re":
                rr = item[1]
                rw = abs(rr.x1 - rr.x0)
                rh = abs(rr.y1 - rr.y0)
                rect_dims.append((rw, rh))
                has_rect = True
            elif kind == "c":
                has_circle = True

    # Default bounding box centre
    rects = [drawings[k].get("rect") for k in cluster_idx if drawings[k].get("rect")]
    if not rects:
        return 0, 0, 0, "I", 12.0
    u_x0 = min(r.x0 for r in rects)
    u_y0 = min(r.y0 for r in rects)
    u_x1 = max(r.x1 for r in rects)
    u_y1 = max(r.y1 for r in rects)
    cx = (u_x0 + u_x1) / 2
    cy = (u_y0 + u_y1) / 2
    w_pt = u_x1 - u_x0
    h_pt = u_y1 - u_y0
    depth_pt = max(w_pt, h_pt)
    depth_in = depth_pt * scale_ratio / 72.0
    
    if depth_in < 4.0:
        depth_in = 8.0
    elif depth_in > 48.0:
        depth_in = 14.0

    rotation = 0
    symbol_type = "I"

    if has_circle:
        symbol_type = "PIPE"
        return cx, cy, 0, symbol_type, depth_in

    if has_rect and not lines:
        symbol_type = "BOX"
        return cx, cy, 0, symbol_type, depth_in

    if len(lines) >= 3:
        angles = []
        for (lx1, ly1, lx2, ly2) in lines:
            dx = lx2 - lx1
            dy = ly2 - ly1
            length = math.hypot(dx, dy)
            if length > 1.5:
                angle = math.degrees(math.atan2(dy, dx)) % 180.0
                angles.append((angle, length, (lx1, ly1, lx2, ly2)))
        
        best_angle = 0
        best_count = 0
        for angle, _, _ in angles:
            count = 0
            for a, _, _ in angles:
                diff = abs(angle - a) % 180.0
                if min(diff, 180.0 - diff) <= 20.0:
                    count += 1
            if count > best_count:
                best_count = count
                best_angle = angle
        
        flange_lines = []
        web_lines = []
        for a, l, line in angles:
            diff = abs(best_angle - a) % 180.0
            if min(diff, 180.0 - diff) <= 20.0:
                flange_lines.append(line)
            elif abs(min(diff, 180.0 - diff) - 90.0) <= 20.0:
                web_lines.append(line)

        ref_cx, ref_cy = cx, cy
        if web_lines:
            web_xs = [ (ln[0] + ln[2])/2 for ln in web_lines ]
            web_ys = [ (ln[1] + ln[3])/2 for ln in web_lines ]
            ref_cx = sum(web_xs) / len(web_xs)
            ref_cy = sum(web_ys) / len(web_ys)
            
            web_angles = []
            for ln in web_lines:
                web_angles.append(math.degrees(math.atan2(ln[3] - ln[1], ln[2] - ln[0])) % 180.0)
            if web_angles:
                avg_web_angle = sum(web_angles) / len(web_angles)
                rotation = min([0, 45, 90, 135, 180], key=lambda a: abs(avg_web_angle - a)) % 180
        else:
            rotation = min([0, 45, 90, 135, 180], key=lambda a: abs(best_angle - a)) % 180
            rotation = (rotation + 90) % 180

        if len(flange_lines) >= 2:
            rad = math.radians(best_angle + 90)
            nx, ny = math.cos(rad), math.sin(rad)
            projections = []
            for ln in flange_lines:
                mx = (ln[0] + ln[2]) / 2
                my = (ln[1] + ln[3]) / 2
                projections.append(mx * nx + my * ny)
            projections.sort()
            dist_pt = projections[-1] - projections[0]
            if 3.0 < dist_pt < 60.0:
                depth_in = dist_pt * scale_ratio / 72.0
                
        return ref_cx, ref_cy, rotation, "I", depth_in

    return cx, cy, rotation, symbol_type, depth_in


# ── Column symbol detection (I/H cross-section marks in vector drawings) ──────
def detect_column_symbols(page, scale_ratio: float = 96, is_foundation_plan: bool = False,
                          plan_bounds: tuple = None):
    """
    Detect the small I-section / W-section plan-view symbols drawn in the PDF.

    plan_bounds: (x0, y0, x1, y1) of the actual plan area, excluding the
    title block, dimension strings, and margin notes. This detector used to
    scan the ENTIRE page unconditionally -- every other symbol/profile
    detector in this pipeline (extract_profiles, etc.) already respects
    plan_bounds, but this one never did, so title-block logos, north-arrow
    callouts, and dimension-string tick marks near the sheet border could
    get misdetected as column symbols and show up as extra phantom columns
    scattered outside the building footprint. Optional (defaults to no
    filtering) so callers that don't have plan_bounds yet still work.
    ...

    is_foundation_plan: when True, ALSO accepts small unfilled diamond/square
    outline marks (4-line closed shapes with no dark fill) as column symbols.
    Foundation/footing plans mark column bases with an outline footing/pier
    symbol (e.g. "F1", "P1"), not the solid-black steel column plan mark this
    function was originally built around -- without this, every column on a
    foundation plan except the rare coincidental match was silently rejected
    by the "un-filled outlines are ignored" rule below, which exists
    specifically to keep framing-plan dimension/annotation boxes from being
    mistaken for columns. That rule is correct for framing plans; it's wrong
    for foundation plans, where the real column marks ARE unfilled outlines.
    Scoped to this flag (not a global change) so framing-plan detection,
    already tuned and verified, is untouched.
    """
    try:
        drawings = page.get_drawings()
    except Exception:
        return []

    # ── Scale-aware thresholds ────────────────────────────────────────────────
    _ipt = 72.0 / max(scale_ratio, 1)

    SYM_MIN_PT = max(3, 3.0 * _ipt)
    SYM_MAX_PT = 48.0 * _ipt
    EPS = max(4, 6.0 * _ipt)

    raw = []

    def _ang_diff(a, b):
        d = abs(a - b) % 180.0
        return min(d, 180.0 - d)

    def _has_IH_pattern(angles, lengths=None, tol=20.0):
        """
        Root cause fix (2026-07-17, Stage 6): this test used to accept ANY
        shape with >=2 near-parallel + >=1 near-perpendicular line segments
        -- which is trivially true for every rectangle, square, and diamond
        (a rotated square), not just a real steel column plan mark. That's
        the exact bug behind "the round and diamond looking shape is not a
        column", flagged at the very start of this rebuild.

        A real I/H section plan symbol has a genuine flange/web geometry:
        two long flange segments joined by a distinctly SHORTER web
        segment (true for every real W/HSS section -- the web width is
        always a small fraction of the flange span). A closed box's four
        sides, by contrast, are all roughly the same length -- there is no
        long/short disparity. When segment lengths are available, require
        that at least one "perpendicular" segment be meaningfully shorter
        (< 45% of the average "parallel" segment length) than the parallel
        group it's paired with -- this is what actually distinguishes an
        open I/H glyph from a closed rectangle/diamond outline, using
        geometry that was already being computed, not a new detection
        pass. `lengths=None` preserves the old angle-only behavior for any
        caller that hasn't been updated to pass lengths yet.

        45% (not a looser 60%) specifically because a moderately elongated
        CLOSED box (e.g. a 2:1 rectangle, short side exactly half the long
        side) would otherwise still slip through at 60% purely from its own
        aspect ratio, with no real flange/web relationship at all -- tested
        and confirmed this exact failure mode during Stage 6 (2026-07-17)
        before tightening the threshold. A real W/HSS section's web is
        drawn distinctly thinner than that relative to its flange span in
        every plan-view icon convention observed this session. This is a
        calibrated threshold, not a proven physical constant -- same
        category as other tuned tolerances in this file (see
        COLUMN_SNAP_TOL_FT, TOS_MATCH_TOL_FT elsewhere) -- revisit if a real
        drawing surfaces a genuine I/H icon this rejects.
        """
        for idx_a, a in enumerate(angles):
            par_idxs = [j for j, b in enumerate(angles) if _ang_diff(a, b) <= tol]
            perp_idxs = [j for j, b in enumerate(angles) if abs(_ang_diff(a, b) - 90.0) <= tol]
            if len(par_idxs) >= 2 and len(perp_idxs) >= 1:
                if lengths is None:
                    return True
                par_lens = [lengths[j] for j in par_idxs if j < len(lengths)]
                perp_lens = [lengths[j] for j in perp_idxs if j < len(lengths)]
                if not par_lens or not perp_lens:
                    # Length data incomplete for this candidate -- fall back
                    # to the angle-only signal rather than silently reject.
                    return True
                par_avg = sum(par_lens) / len(par_lens)
                if par_avg > 0 and any(pl < par_avg * 0.45 for pl in perp_lens):
                    return True
        return False

    for i, d in enumerate(drawings):
        rect = d.get("rect")
        if rect is None:
            continue
        w, h = rect.width, rect.height

        # Column symbol bounding box: within scale-derived size range.
        # SYM_MIN_PT: minimum meaningful column symbol dimension (≥3" real).
        # SYM_MAX_PT: maximum (largest W/HSS section at this scale).
        if not (SYM_MIN_PT < w < SYM_MAX_PT and SYM_MIN_PT < h < SYM_MAX_PT):
            continue

        # Reject anything outside the actual plan area (title block, north
        # arrow, dimension strings near the sheet border) -- small margin
        # (2x EPS-ish) so a real column symbol whose bbox straddles the
        # plan-boundary line isn't clipped.
        if plan_bounds is not None:
            _cx_chk = (rect.x0 + rect.x1) / 2
            _cy_chk = (rect.y0 + rect.y1) / 2
            _margin = 20.0
            if not (plan_bounds[0] - _margin <= _cx_chk <= plan_bounds[2] + _margin
                    and plan_bounds[1] - _margin <= _cy_chk <= plan_bounds[3] + _margin):
                continue

        # Store the overall DRAWING bounding box alongside the centre.
        # We accumulate rects per cluster and recompute the centre from
        # the union bbox — this avoids the sub-path averaging drift that
        # pulls the column position left/right when one flange has more
        # sub-paths than the other.
        cx = (rect.x0 + rect.x1) / 2
        cy = (rect.y0 + rect.y1) / 2
        # keep the full rect so clustering can take the union bbox
        _raw_rect = (rect.x0, rect.y0, rect.x1, rect.y1)

        # ── Check drawing fill colour up-front ───────────────────────────────
        # Column plan marks are solid BLACK fills.
        # Dimension ticks / annotation boxes are un-filled (fill=None) or light.
        # We read the fill once here and use it inside the item loop.
        drawing_fill       = d.get("fill")
        drawing_brightness = 1.0   # assume light until proven dark
        if drawing_fill is not None and len(drawing_fill) >= 3:
            drawing_brightness = (drawing_fill[0] +
                                  drawing_fill[1] +
                                  drawing_fill[2]) / 3

        # Real footing/pier marks on this project's foundation plans are
        # drawn DASHED (visibly confirmed against the actual sheet) -- grid
        # extension lines, dimension-string boxes, and other solid-line
        # annotation near the sheet border are not. Used below to keep the
        # foundation-plan-only relaxed rules from accepting solid-line
        # clutter as a footing mark.
        _dashes = d.get("dashes") or ""
        _is_dashed = _dashes not in ("", "[] 0")

        items     = d.get("items", [])
        has_curve = False
        n_lines   = 0
        h_count   = 0   # number of horizontal segments (flanges)
        v_count   = 0   # number of vertical segments (web)
        seg_angles = []  # angle (mod 180°) of every line segment — for the
                         # rotation-invariant I/H test below
        seg_lengths = []  # parallel to seg_angles -- see Stage 6 fix below

        for item in items:
            kind = item[0]
            if kind == "c":
                has_curve = True   # arc/circle → callout bubble, not a column
                break
            elif kind == "l":
                n_lines += 1
                try:
                    p1, p2 = item[1], item[2]
                    dx = abs(p2.x - p1.x)
                    dy = abs(p2.y - p1.y)
                    _seg_len = math.hypot(dx, dy)
                    if _seg_len < 2:
                        continue
                    seg_angles.append(math.degrees(math.atan2(p2.y - p1.y,
                                                              p2.x - p1.x)) % 180.0)
                    seg_lengths.append(_seg_len)
                    if dx > dy * 1.5:
                        h_count += 1
                    elif dy > dx * 1.5:
                        v_count += 1
                except Exception:
                    continue
            elif kind == "re":
                # PDF rectangle primitive.
                # ONLY accept if the drawing has a VERY DARK (near-black) fill —
                # this is the signature of a structural column plan mark.
                # Un-filled outlines and light-coloured annotation boxes are
                # ignored -- EXCEPT on foundation plans, where the real
                # footing/pier mark IS an unfilled outline (often drawn as a
                # single rotated "re" primitive rather than 4 separate line
                # segments), so the fill requirement would otherwise silently
                # drop it before it's even counted as a candidate shape.
                if drawing_brightness < 0.25 or is_foundation_plan:
                    try:
                        rr = item[1]
                        rw = abs(rr.x1 - rr.x0)
                        rh = abs(rr.y1 - rr.y0)
                        ra = rw / rh if rh > 0 else 0
                        # Must be reasonably square and large enough to be a mark
                        if rw >= 4 and rh >= 4 and 0.25 < ra < 4.0:
                            h_count += 2
                            v_count += 1
                            n_lines += 4
                            # Root cause fix (2026-07-17, Stage 6 -- this is
                            # the exact bug behind "the round and diamond
                            # looking shape is not a column", flagged at the
                            # very start of this rebuild): a PDF "re"
                            # rectangle primitive is, by definition, a
                            # CLOSED four-sided box -- a plain square, a
                            # square rotated 45 degrees so it renders as a
                            # diamond, a generic annotation pad, anything.
                            # It is NOT an I/H flange-web glyph, which is an
                            # OPEN shape (two flange segments that never
                            # touch, joined only by a thin web). The line
                            # this replaces injected a synthetic
                            # seg_angles=[0, 0, 90] for EVERY such rectangle
                            # regardless of what it actually was, which
                            # manufactured a fake "verified I/H pattern"
                            # signal for any roughly-square box -- exactly
                            # what let round/diamond footing outlines and
                            # generic pads get accepted as if they were real
                            # steel column marks. A rectangle primitive
                            # shape is still a legitimate candidate mark --
                            # it just needs to go through the actual
                            # box-shaped rules below (filled_rect for a dark
                            # solid square, foundation_outline for an
                            # unfilled one on a foundation plan), which
                            # already exist, are already correctly gated on
                            # fill/size/aspect, and do not depend on
                            # pretending this is an I/H pattern to fire.
                    except Exception:
                        pass

        aspect = w / h if h > 0 else 0

        # ── Accept I/H shape (rotation-invariant) ────────────────────────────
        # ≥2 parallel flange segments + ≥1 perpendicular web segment at ANY
        # orientation.  This detects the column symbol whether it is upright OR
        # rotated to any angle (skewed grids, canopy/angled framing) — the case
        # where the old strict horizontal/vertical test missed columns, leaving
        # beams with no centre to snap to.
        if not has_curve and _has_IH_pattern(seg_angles, lengths=seg_lengths):
            raw.append((cx, cy, _raw_rect, i, "ih_pattern"))
            continue

        # ── Accept small FILLED rectangle (solid black plan mark only) ────────
        if (not has_curve and n_lines == 4 and 0.5 < aspect < 2.0
                and w < 28 and h < 28 and drawing_brightness < 0.25):
            raw.append((cx, cy, _raw_rect, i, "filled_rect"))
            continue

        # ── Accept small CIRCLED I/H symbol ───────────────────────────────────
        if has_curve and _has_IH_pattern(seg_angles, lengths=seg_lengths) and 10 < w < 45 and 10 < h < 45:
            raw.append((cx, cy, _raw_rect, i, "circled_ih"))
            continue

        # ── Foundation plans only: small UNFILLED diamond/square outline ──────
        # (footing/pier mark). Same 4-line, roughly-square-proportioned shape
        # as the filled-rectangle rule above, but with no fill requirement --
        # see the is_foundation_plan docstring note for why this is safe to
        # loosen only here rather than for every page. A dashed-line-style
        # requirement was tried here but PDF exporters don't consistently
        # encode dash arrays in drawing metadata (some real footing marks on
        # some sheets report no dash pattern at all, silently zeroing out
        # every candidate) -- the mark-label-proximity filter below is the
        # real guard against false positives instead.
        #
        # Size bound fix (2026-07-17, Stage 6): this used to additionally
        # require w < 30 and h < 30 -- a fixed constant, not derived from
        # scale, tighter than the SYM_MIN_PT..SYM_MAX_PT envelope every
        # candidate already had to pass to reach this point at all. On a
        # project that draws footings at true plan scale (documented
        # below -- an 11'-6" footing is ~103pt at 1/8"=1'-0", confirmed on
        # a real sheet), that redundant 30pt cap silently rejected footing
        # outlines the scale-aware envelope already correctly allowed
        # through. Live-verified: removing this cap and closing the
        # separate _has_IH_pattern false-positive bug together took a real
        # foundation plan from 49 detected footings down to 5 (the cap
        # alone was hiding the loss) then back up -- see chat trace. Rely
        # on the already-applied, scale-aware SYM_MIN_PT/SYM_MAX_PT bound
        # from the top of this loop instead of a second, inconsistent
        # fixed-pixel limit.
        # ── Small UNFILLED diamond/square outline (footing/pier/pedestal mark) ──
        # Captured as candidate; column_symbol_classifier approves it if nearby structural mark exists.
        if (not has_curve and n_lines == 4 and 0.4 < aspect < 2.5):
            raw.append((cx, cy, _raw_rect, i, "foundation_outline"))

    # ── Fragmented dashed/segmented shape rescue (foundation plans only) ──
    # Confirmed via direct inspection of a real project PDF (Bayhealth
    # Sussex MOB, foundation plan sheet S1.00): some PDF exporters draw a
    # dashed footing outline -- and sometimes the steel column's inner H/I
    # plan-view glyph too -- as MANY separate single-line "drawing" objects
    # (one per dash tick, or one per glyph edge) instead of one dashed
    # stroke or one 4-line path. Every accept rule above evaluates ONE
    # drawing object at a time (_has_IH_pattern needs >=2 parallel + >=1
    # perpendicular segment WITHIN that one drawing; the 4-line rules need
    # n_lines==4 within that one drawing), so a real column whose symbol is
    # authored this way is invisible to every rule above -- confirmed live:
    # roughly half the columns on that sheet (the ones using the square +
    # inner-H/I-glyph convention) got zero detection, while the plain
    # hollow-square footings on the same sheet were fine. Also: that
    # project draws footings at TRUE plan scale (an 11'-6" square footing
    # is ~103pt wide at 1/8"=1'-0"), far past SYM_MAX_PT/the 30pt cap above
    # -- both of which assume a compact schematic icon, not a true-scale
    # outline -- so this rescue pass uses its own, real-world-footing-sized
    # envelope (up to ~20 real feet) rather than SYM_MAX_PT.
    #
    # Fix: chain-cluster small isolated line fragments by endpoint
    # proximity (dash gaps run ~9pt on that sheet; eps=12 covers that with
    # margin, and also bridges directly-touching glyph edges whose shared
    # vertices are ~0pt apart), then re-run the same angle-histogram tests
    # against each fragment group's AGGREGATE geometry instead of one
    # drawing at a time. Purely additive: only touches drawings with
    # exactly one unfilled line item, which no rule above ever accepts on
    # its own, so this cannot change any already-working detection.
    if is_foundation_plan:
        _FOOTING_MAX_PT = max(SYM_MAX_PT, 20.0 * 12.0 * _ipt)  # ~20 real ft ceiling
        _FRAG_EPS = 12.0
        frag_idx: list[int] = []
        frag_pts: list[tuple] = []  # (x0, y0, x1, y1) per fragment
        for i, d in enumerate(drawings):
            items = d.get("items", [])
            if len(items) != 1 or items[0][0] != "l" or d.get("fill") is not None:
                continue
            p1, p2 = items[0][1], items[0][2]
            seg_len = math.hypot(p2.x - p1.x, p2.y - p1.y)
            if seg_len < 2 or seg_len > _FOOTING_MAX_PT:
                continue
            if plan_bounds is not None:
                _mcx, _mcy = (p1.x + p2.x) / 2, (p1.y + p2.y) / 2
                if not (plan_bounds[0] - 20 <= _mcx <= plan_bounds[2] + 20
                        and plan_bounds[1] - 20 <= _mcy <= plan_bounds[3] + 20):
                    continue
            frag_idx.append(i)
            frag_pts.append((p1.x, p1.y, p2.x, p2.y))

        # Performance (2026-07-28, user-reported multi-minute extraction on
        # large sheets): same O(n^2) issue as the EPS-cluster fix above --
        # this loop compared every fragment's endpoints against every other
        # fragment's endpoints (4 hypot() calls per pair). On a foundation
        # plan, `frag_idx` is every unfilled single-line drawing object on
        # the whole sheet (dash ticks, hatch lines, footing outlines), which
        # can run into the thousands -- this was the single largest
        # contributor to the 12M+ hypot() calls measured on one profiled
        # sheet. Spatial-grid bucket the fragment ENDPOINTS (cell size =
        # _FRAG_EPS) so only fragments with an endpoint in the same/adjacent
        # cell are ever distance-checked. Produces the identical fusion
        # result as the brute-force version -- same _FRAG_EPS threshold,
        # same 4-endpoint-pair test, same flood-fill/union semantics.
        _frag_grid: dict = {}
        for _fi, (fx0, fy0, fx1, fy1) in enumerate(frag_pts):
            for (fx, fy) in ((fx0, fy0), (fx1, fy1)):
                _fk = (int(fx // _FRAG_EPS), int(fy // _FRAG_EPS))
                _frag_grid.setdefault(_fk, set()).add(_fi)

        def _frag_candidates(idx):
            fx0, fy0, fx1, fy1 = frag_pts[idx]
            seen_cand = set()
            for (fx, fy) in ((fx0, fy0), (fx1, fy1)):
                gx, gy = int(fx // _FRAG_EPS), int(fy // _FRAG_EPS)
                for dgx in (-1, 0, 1):
                    for dgy in (-1, 0, 1):
                        seen_cand.update(_frag_grid.get((gx + dgx, gy + dgy), ()))
            return seen_cand

        _fused = [False] * len(frag_idx)
        for a in range(len(frag_idx)):
            if _fused[a]:
                continue
            group = [a]
            _fused[a] = True
            queue = [a]
            while queue:
                cur = queue.pop()
                cx0, cy0, cx1, cy1 = frag_pts[cur]
                for b in _frag_candidates(cur):
                    if _fused[b]:
                        continue
                    bx0, by0, bx1, by1 = frag_pts[b]
                    if (math.hypot(cx0 - bx0, cy0 - by0) < _FRAG_EPS or
                            math.hypot(cx0 - bx1, cy0 - by1) < _FRAG_EPS or
                            math.hypot(cx1 - bx0, cy1 - by0) < _FRAG_EPS or
                            math.hypot(cx1 - bx1, cy1 - by1) < _FRAG_EPS):
                        _fused[b] = True
                        group.append(b)
                        queue.append(b)

            if len(group) < 3:
                continue  # too few fragments to be a real shape (stray tick/noise)

            g_angles = []
            gxs: list[float] = []
            gys: list[float] = []
            for gi in group:
                x0, y0, x1, y1 = frag_pts[gi]
                gxs += [x0, x1]
                gys += [y0, y1]
                if math.hypot(x1 - x0, y1 - y0) >= 2:
                    g_angles.append(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0)
            gw, gh = max(gxs) - min(gxs), max(gys) - min(gys)
            if gw <= 0 or gh <= 0:
                continue
            g_aspect = gw / gh
            if not (SYM_MIN_PT < gw < _FOOTING_MAX_PT and SYM_MIN_PT < gh < _FOOTING_MAX_PT):
                continue
            if not (0.4 < g_aspect < 2.5):
                continue
            if not (_has_IH_pattern(g_angles) or len(group) >= 4):
                continue

            # Register every fragment in this group as its own raw
            # candidate at ITS OWN true center -- the existing EPS-based
            # cluster step right below re-merges them into one physical
            # column, exactly like it already does for multi-sub-path
            # filled-rectangle symbols.
            for gi in group:
                x0, y0, x1, y1 = frag_pts[gi]
                _fcx, _fcy = (x0 + x1) / 2, (y0 + y1) / 2
                raw.append((_fcx, _fcy, (x0, y0, x1, y1), frag_idx[gi], "fragmented_outline"))

    # Deduplicate using EXPANDING cluster (DBSCAN-style, eps=15pt).
    #
    # WHY NOT a fixed radius:
    #   • Some CAD exports draw each column symbol as 6-8 separate filled-rectangle
    #     sub-paths (one per flange/web piece). Sub-paths of the SAME symbol are
    #     typically 8-15pt apart from each other.
    #   • A simple fixed-radius check from the SEED only merges points within that
    #     radius of the first point. If the cluster spans 70pt but each step is
    #     only 10pt, a 12pt seed-radius misses outer sub-paths.
    #   • A 60pt fixed radius merges real adjacent columns when the drawing scale
    #     is small (columns can be 40-50pt apart on some sheets).
    #
    # EXPANDING CLUSTER solution:
    #   eps=15pt — small enough to never bridge two real columns (always >30pt apart
    #   at any typical drawing scale), large enough to chain sub-paths of the same
    #   symbol together step-by-step regardless of total symbol span.
    #
    # Foundation plans widen this to 30pt: a footing mark here is drawn as TWO
    # separate shapes -- the dashed footing outline (square) and the small
    # I-tick column mark at its centre -- which are further apart (their
    # separate drawing objects' centres don't coincide as tightly as one
    # symbol's own sub-paths do) than 15pt reliably bridges, producing two
    # separate "columns" for the same physical footing instead of one. Still
    # well under real footing-to-footing spacing (multiple feet = tens of pt)
    # so this doesn't risk merging two adjacent real footings together.
    EPS = 30 if is_foundation_plan else 15

    # Performance (2026-07-28, user-reported: full extraction taking 3-4
    # minutes on a large/complex sheet): the flood-fill below used to scan
    # ALL of `raw` for every point popped from the queue -- worst case
    # O(len(raw)^2) distance checks. Profiled live on a real drawing: over
    # 12 MILLION math.hypot() calls from this loop alone on a single
    # mid-size sheet, and this was the single largest cost in the entire
    # analyse_pdf pipeline by a wide margin. A bigger/denser sheet (more
    # raw vector sub-paths) scales quadratically, which is exactly what
    # turns a big drawing into a multi-minute extraction.
    #
    # Fix: bucket every raw candidate into an EPS-sized spatial grid first.
    # Any two points within EPS of each other must fall in the same or an
    # immediately-adjacent grid cell (cell size == EPS), so the neighbor
    # search only has to check the 3x3 block of cells around a point instead
    # of every other point on the sheet. This produces the EXACT SAME
    # clusters as the brute-force version -- same EPS threshold, same
    # flood-fill/union semantics -- it only changes how neighbors are found,
    # not which points count as neighbors.
    _grid: dict = {}
    for _idx, _r in enumerate(raw):
        _key = (int(_r[0] // EPS), int(_r[1] // EPS))
        _grid.setdefault(_key, []).append(_idx)

    def _grid_neighbors(idx):
        px, py = raw[idx][0], raw[idx][1]
        gx, gy = int(px // EPS), int(py // EPS)
        for dgx in (-1, 0, 1):
            for dgy in (-1, 0, 1):
                for j in _grid.get((gx + dgx, gy + dgy), ()):
                    if not used[j] and math.hypot(px - raw[j][0], py - raw[j][1]) < EPS:
                        yield j

    symbols = []
    used = [False] * len(raw)
    for i in range(len(raw)):
        if used[i]:
            continue
        cluster_idx = [i]
        used[i] = True
        queue = [i]
        while queue:
            cur_idx = queue.pop()
            for j in _grid_neighbors(cur_idx):
                used[j] = True
                cluster_idx.append(j)
                queue.append(j)

        ref_cx, ref_cy, rotation, symbol_type, depth_in = refine_column_geometry(
            drawings, [raw[k][3] for k in cluster_idx], scale_ratio)

        # Aggregate shape signals across every raw sub-path in this cluster
        # -- the Symbol Classification Engine (column_symbol_classifier.py)
        # needs the union bbox (for aspect-ratio and size-relative-to-sheet
        # checks) and whether ANY sub-path had a curve or a dash, since a
        # symbol's sub-paths were collected without this being tracked
        # per-symbol before now.
        _bxs = [raw[k][2][0] for k in cluster_idx] + [raw[k][2][2] for k in cluster_idx]
        _bys = [raw[k][2][1] for k in cluster_idx] + [raw[k][2][3] for k in cluster_idx]
        _bbox = (min(_bxs), min(_bys), max(_bxs), max(_bys))
        _has_curve_any = False
        _is_dashed_any = False
        # 2026-07-17: a detail/section-reference bubble is a UNIVERSAL
        # drafting convention (AIA/NCS) regardless of firm or drawing --
        # a circle/hex/diamond bisected by one roughly-horizontal divider
        # line, with a detail number above it and a sheet number below it.
        # Two real projects this session each broke a text-pattern-based
        # detection of this ("S0300" 4-digit, then "S2.03" dotted) because
        # every firm writes its sheet numbers differently -- fixing the
        # regex per-format is the exact wrong approach (hardcoding to a
        # PDF), since the next drawing will just use a third convention.
        # The SHAPE signature is universal and content-independent: detect
        # the divider bar itself, not what the two numbers say. A real
        # column/footing mark's own sub-paths never contain a line that
        # spans most of the symbol's own width while sitting near its
        # vertical center -- that specific geometry only shows up on a
        # bisected reference bubble.
        # Aggregate horizontal, near-vertical-center line length instead of
        # requiring ONE continuous segment -- a divider bar drawn with a
        # dashed/hidden linetype (common for internal ruling lines) or
        # fragmented into multiple short PDF path segments would never
        # individually clear a single-segment length threshold, even
        # though together they trace the same divider. Summing handles
        # both a solid divider and a dashed one the same way.
        _divider_len = 0.0
        _bbox_w_chk = _bbox[2] - _bbox[0]
        _bbox_h_chk = _bbox[3] - _bbox[1]
        _bbox_mid_y_chk = (_bbox[1] + _bbox[3]) / 2
        for k in cluster_idx:
            _d = drawings[raw[k][3]]
            for _item in _d.get("items", []):
                if _item[0] == "c":
                    _has_curve_any = True
                elif _item[0] == "l":
                    _p1, _p2 = _item[1], _item[2]
                    _lx1, _ly1, _lx2, _ly2 = _p1.x, _p1.y, _p2.x, _p2.y
                    _llen = math.hypot(_lx2 - _lx1, _ly2 - _ly1)
                    if _bbox_w_chk > 0 and _bbox_h_chk > 0:
                        _is_horiz = abs(_ly2 - _ly1) <= max(2.0, _llen * 0.12)
                        _mid_y = (_ly1 + _ly2) / 2
                        _near_vcenter = abs(_mid_y - _bbox_mid_y_chk) <= _bbox_h_chk * 0.35
                        if _is_horiz and _near_vcenter:
                            _divider_len += _llen
            _dashes = _d.get("dashes") or ""
            if _dashes not in ("", "[] 0"):
                _is_dashed_any = True
        _has_divider_bar = _bbox_w_chk > 0 and _divider_len >= _bbox_w_chk * 0.55

        # Which shape-acceptance rule(s) matched this cluster's sub-paths --
        # the real signal for "is this actually an I/H column icon" rather
        # than refine_column_geometry's symbol_type, which defaults to "I"
        # for ANY non-circle/non-bare-rect shape (including a generic
        # 4-line footing outline), making it unreliable on its own for
        # telling a real column icon apart from a footing outline. See
        # column_symbol_classifier.py.
        _accept_rules = {raw[k][4] for k in cluster_idx if len(raw[k]) > 4}
        _has_ih_pattern = bool(_accept_rules & {"ih_pattern", "circled_ih"})

        # Phase 2 feature extraction (Universal Symbol Library lookup) --
        # classifies this cluster's outer_boundary/inner_geometry/fill_type
        # combination and matches it against the catalog of real-world
        # column symbol styles (hollow square, filled square, square+dot,
        # square+diamond, square+cross, square+I/H, square+inner-square,
        # circle-in-footing, diamond-in-footing, ...) instead of only the
        # four accept_rules above. Purely additive/informational at this
        # stage -- see column_feature_extraction.py and
        # column_symbol_library.py. Never lets a candidate through or
        # blocks one on its own; downstream classification/validation
        # treats it as one more signal.
        try:
            from app.engineering.column_feature_extraction import extract_cluster_features
            _features = extract_cluster_features(drawings, [raw[k][3] for k in cluster_idx])
        except Exception:
            _features = {"outer_boundary": None, "inner_geometry": None, "fill_type": None,
                         "library_match": None, "library_name": None,
                         "expected_member_type": None, "library_confidence": 0.0}

        # ── Inner column symbol centering (foundation plan fix) ─────────────
        # On foundation plans the cluster often merges a large outer shape
        # (footing outline, pile cap rectangle, grade-beam) with a small
        # inner column square or I-tick.  refine_column_geometry returns the
        # UNION bounding-box centre, which drifts toward the outer shape and
        # produces a marker that floats beside rather than ON the column.
        #
        # Strategy (priority order):
        #   1. DARK FILLED rect  — a small rect with fill brightness < 0.4 is
        #      almost certainly the solid black/dark-gray column base-plate.
        #      Use its centre first.
        #   2. SMALLEST rect     — if no dark fill found, use the smallest
        #      roughly-square rect (the column inner square is always smaller
        #      than the surrounding footing outline).
        #   3. UNION centroid    — fallback when the cluster has only one
        #      drawing (framing-plan I-column with no footing outline).
        #
        # IMPORTANT: cluster_idx contains indices into `raw`, NOT into
        # `drawings`.  The actual drawing index is raw[_k][3].
        _inner_cx, _inner_cy = ref_cx, ref_cy  # default: union centroid
        if len(cluster_idx) > 1 and is_foundation_plan:
            _best_dark_area = None
            _best_small_area = None
            _dark_cx = _dark_cy = None
            _small_cx = _small_cy = None
            for _k in cluster_idx:
                _dk = raw[_k][3]          # ← correct: drawing index from raw tuple
                _d_obj = drawings[_dk]
                _dr = _d_obj.get("rect")
                if _dr is None:
                    continue
                _dw = abs(_dr.x1 - _dr.x0)
                _dh = abs(_dr.y1 - _dr.y0)
                _da = _dw * _dh
                if _da < 4:               # skip degenerate single-pixel rects
                    continue
                _aspect = _dw / _dh if _dh > 0 else 0
                _dcx = (_dr.x0 + _dr.x1) / 2
                _dcy = (_dr.y0 + _dr.y1) / 2
                # Priority 1: dark filled rect (the actual solid column square)
                _fill = _d_obj.get("fill")
                if _fill is not None and len(_fill) >= 3:
                    _brightness = (_fill[0] + _fill[1] + _fill[2]) / 3
                    if _brightness < 0.4 and (_best_dark_area is None or _da < _best_dark_area):
                        _best_dark_area = _da
                        _dark_cx, _dark_cy = _dcx, _dcy
                # Priority 2: smallest roughly-square rect (inner column box)
                if 0.35 < _aspect < 2.8:
                    if _best_small_area is None or _da < _best_small_area:
                        _best_small_area = _da
                        _small_cx, _small_cy = _dcx, _dcy
            # Apply best result found
            if _dark_cx is not None:
                _inner_cx, _inner_cy = _dark_cx, _dark_cy
            elif _small_cx is not None:
                _inner_cx, _inner_cy = _small_cx, _small_cy
            # else: remains ref_cx/ref_cy (union centroid fallback)

        symbols.append({
            "cx": ref_cx,
            "cy": ref_cy,
            # inner_cx/inner_cy: centre of the SMALLEST rect in this cluster
            # = the actual column/base-plate square, not the outer footing.
            # Used by emit_symbol_columns as raw_x/raw_y so the frontend
            # marker lands exactly on the column symbol.
            "inner_cx": _inner_cx,
            "inner_cy": _inner_cy,
            "rotation": rotation,
            "symbol": symbol_type,
            "depth_in": depth_in,
            "accept_rules": sorted(_accept_rules),
            "has_ih_pattern": _has_ih_pattern,
            "bbox": _bbox,
            # Real detected bounding-box size (page-pt units, same space as
            # cx/cy) -- Stage 6 Part 2: lets the 2D overlay render a footing/
            # box symbol AT THE ACTUAL SIZE OF THE REAL SHAPE instead of a
            # generic fixed-size glyph, matching SteelGenie's convention
            # (verified live: SteelGenie sizes footing outlines to the real
            # detected mark, but keeps I/H column icons a small fixed
            # schematic size regardless of the real glyph's on-page size).
            "bbox_w": _bbox[2] - _bbox[0],
            "bbox_h": _bbox[3] - _bbox[1],
            "has_curve": _has_curve_any,
            "is_dashed": _is_dashed_any,
            "has_divider_bar": _has_divider_bar,
            "outer_boundary": _features.get("outer_boundary"),
            "inner_geometry": _features.get("inner_geometry"),
            "fill_type": _features.get("fill_type"),
            "library_match": _features.get("library_match"),
            "library_name": _features.get("library_name"),
            "expected_member_type": _features.get("expected_member_type"),
            "library_confidence": _features.get("library_confidence", 0.0),
        })

    # Symbol Classification Engine: distinguishes real structural-column
    # candidates (steel column plan marks, isolated footings, pile caps)
    # from everything else a foundation/framing plan draws that can
    # coincidentally match the shape rules above -- grid bubbles, detail/
    # section callouts, dimension ticks, equipment pads, wall footings,
    # annotations. This is the gatekeeper the mission calls for: nothing
    # downstream (mark-filter, emit_symbol_columns) should ever see a
    # candidate this stage rejects. See column_symbol_classifier.py.
    try:
        from app.engineering.column_symbol_classifier import classify_and_filter_symbols
        symbols, rejected = classify_and_filter_symbols(symbols, page, is_foundation_plan=is_foundation_plan)
        print(f"[SYMBOLS] Column symbols detected (pre mark-filter): {len(symbols)} "
              f"(classifier rejected {len(rejected)})")
    except Exception as _e:
        print(f"[SYMBOLS] Classifier unavailable ({_e}), skipping classification stage")
        print(f"[SYMBOLS] Column symbols detected (pre mark-filter): {len(symbols)}")

    return symbols


def detect_foundation_footings_grid(page, plan_bounds, scale_ratio: float = 96):
    """
    Foundation-plan footing/column detector, grid-intersection anchored.

    Why this exists (2026-07-20, built after the symbol-shape detector was
    shown live to miss ~2/3 of the real footings on a real foundation plan
    and to misplace the ones it did find):

    A foundation plan is the one sheet where the drawing itself tells you
    exactly where every column is -- the general note says verbatim
    "FOUNDATIONS, COLUMNS AND PIERS ARE CENTERED ON THE GRID LINE". So the
    single most reliable place to look for a footing/column is a grid
    INTERSECTION, and the correct place to PLACE its marker is the
    intersection point itself (dead-center on the footing), not the drifting
    centroid of whatever vector sub-paths a shape detector happened to
    cluster. This inverts the old approach: instead of finding shapes and
    hoping they sit on the grid, we walk the grid and ask "is there footing
    ink here?".

    Two stages:
      1. Build a CLEAN grid from the sheet's own grid bubbles. Grid bubbles
         are the large-font (>=11pt) single-token labels ("1".."8", "A".."F",
         "C.1") printed in one row along the top/bottom (numbers -> vertical
         grid lines) and one column along the left/right (letters ->
         horizontal grid lines). Restricting to the dominant large-font
         perimeter band drops the small-font (~9.5pt) detail/section-bubble
         numbers scattered through the interior that pollute the generic
         text-grid extractor.
      2. At each intersection, count nearby short vector fragments (the
         dashed footing outline + inner square + column I-mark are all drawn
         as many small line segments). A real footing concentrates many
         fragments spread across a footing-sized box in BOTH axes; a bare
         wall/grid-line crossing produces only a thin line of fragments along
         one axis. Require enough fragments AND real 2-D extent.

    Returns a list of dicts: {cx, cy, grid_ref, n_frags, span_w, span_h}.
    Deliberately foundation-plan-only and self-contained -- it does not touch
    the framing-plan beam-convergence detector or the shape/symbol detector.
    """
    import re as _re
    bx0, by0, bx1, by1 = plan_bounds

    # ── Stage 1: clean grid from large-font perimeter bubbles ────────────────
    try:
        td = page.get_text("dict")
    except Exception:
        return []
    _NUM = _re.compile(r'^[0-9]{1,2}(?:\.[0-9])?$')
    _LET = _re.compile(r'^[A-Z]{1,2}(?:\.[0-9])?$')
    nums: list[tuple] = []
    lets: list[tuple] = []
    for b in td.get("blocks", []):
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                t = s["text"].strip()
                fs = s.get("size", 0)
                if fs < 11 or not t or len(t) > 4:
                    continue
                cx = (s["bbox"][0] + s["bbox"][2]) / 2
                cy = (s["bbox"][1] + s["bbox"][3]) / 2
                if _NUM.match(t):
                    nums.append((t, cx, cy))
                elif _LET.match(t):
                    lets.append((t, cx, cy))

    def _dominant_band(pts, coord_idx, tol=15.0):
        """Keep only the points in the single densest coordinate band (the
        printed grid edge); return their opposite-axis positions + labels,
        plus the size of that band (how many labels actually shared the
        coordinate) so the caller can judge how confident this reading is."""
        if not pts:
            return [], {}, 0
        buck: dict[int, list] = {}
        for p in pts:
            buck.setdefault(round(p[coord_idx] / tol), []).append(p)
        best = max(buck.values(), key=len)
        # opposite axis carries the grid-line position
        pos_idx = 2 if coord_idx == 1 else 1
        best.sort(key=lambda p: p[pos_idx])
        out_pos: list[float] = []
        out_lab: dict[float, str] = {}
        for p in best:
            v = p[pos_idx]
            if not out_pos or abs(v - out_pos[-1]) > 18:
                out_pos.append(v)
                out_lab[v] = p[0]
        return out_pos, out_lab, len(best)

    # Which set of bubbles ("numbers" or "letters") labels the VERTICAL grid
    # lines (printed in a row along the top/bottom, sharing one Y) versus the
    # HORIZONTAL grid lines (printed in a column along a side, sharing one X)
    # is a drawing-convention choice, not a fixed rule -- most sheets number
    # the columns and letter the rows, but plenty do the opposite. Hard-coding
    # "numbers = vertical" broke every foundation plan drawn the other way
    # (grid detector would only ever find 1 usable point per axis and bail
    # out to the much less accurate fallback). Instead, try BOTH band
    # hypotheses for each label set and keep whichever reading actually found
    # more labels sharing a coordinate -- that is the one describing how this
    # specific sheet was drawn.
    nums_as_row, nums_as_row_lab, nums_row_n = _dominant_band(nums, 2)   # row along top/bottom
    nums_as_col, nums_as_col_lab, nums_col_n = _dominant_band(nums, 1)   # column along a side
    lets_as_row, lets_as_row_lab, lets_row_n = _dominant_band(lets, 2)
    lets_as_col, lets_as_col_lab, lets_col_n = _dominant_band(lets, 1)

    nums_is_row = nums_row_n >= nums_col_n
    lets_is_row = lets_row_n >= lets_col_n

    if nums_is_row and not lets_is_row:
        # Standard convention: numbers along the top -> vertical lines;
        # letters along a side -> horizontal lines.
        v_grid, v_lab = nums_as_row, nums_as_row_lab
        h_grid, h_lab = lets_as_col, lets_as_col_lab
    elif lets_is_row and not nums_is_row:
        # Inverted convention: letters along the top -> vertical lines;
        # numbers along a side -> horizontal lines.
        v_grid, v_lab = lets_as_row, lets_as_row_lab
        h_grid, h_lab = nums_as_col, nums_as_col_lab
    else:
        # Ambiguous (both read as "row" or both as "column") -- fall back to
        # the historical assumption rather than guess.
        v_grid, v_lab = nums_as_row, nums_as_row_lab
        h_grid, h_lab = lets_as_col, lets_as_col_lab

    if len(v_grid) < 2 or len(h_grid) < 2:
        # Not enough grid to anchor to -- caller falls back to the old path.
        return []

    # ── Stage 2: footing ink at each intersection ────────────────────────────
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    frags: list[tuple] = []
    for d in drawings:
        for it in d.get("items", []):
            if it[0] == "l":
                p1, p2 = it[1], it[2]
                seg = math.hypot(p2.x - p1.x, p2.y - p1.y)
                if 3 < seg < 90:
                    frags.append((p1.x, p1.y, p2.x, p2.y,
                                  (p1.x + p2.x) / 2, (p1.y + p2.y) / 2))

    # Scale-aware search radius: footings run ~2-12 ft; at 1/8"=1'-0"
    # (scale_ratio=96) that's ~18-108pt, so a 40pt half-window centered on the
    # intersection comfortably contains the footing outline without reaching
    # into the neighbouring bay (bays are 279pt here). Scale it so the same
    # holds on sheets drawn at other scales.
    _ipt = 72.0 / max(scale_ratio, 1)
    R = max(28.0, 40.0 * (_ipt / (72.0 / 96)))
    MIN_FRAGS = 3
    MIN_SPAN = 6.0
    MIN_ORTHO_SPREAD = 3.0

    # Column callout regex for real columns (C1, C2, BP1, BP2, HSS, PIPE, W...)
    # Pier callouts (P24, P36, F5.0) are pier dimensions, NOT column labels.
    _COL_TEXT_RE = _re.compile(r'^(?:C[0-9]{1,2}[A-Z]?|BP[0-9]{1,2}|HSS\d+.*|PIPE\d+.*|W\d+X\d+.*)$', _re.IGNORECASE)

    out = []
    for gy in h_grid:
        for gx in v_grid:
            xs: list[float] = []
            ys: list[float] = []
            hz_y: list[float] = []   # y-centers of roughly-horizontal fragments
            vt_x: list[float] = []   # x-centers of roughly-vertical fragments
            n = 0
            for x1, y1, x2, y2, cx, cy in frags:
                if abs(cx - gx) < R and abs(cy - gy) < R:
                    xs += [x1, x2]
                    ys += [y1, y2]
                    if abs(x2 - x1) >= abs(y2 - y1):
                        hz_y.append(cy)
                    else:
                        vt_x.append(cx)
                    n += 1
            if n < MIN_FRAGS:
                continue
            sw = max(xs) - min(xs)
            sh = max(ys) - min(ys)
            if sw < MIN_SPAN or sh < MIN_SPAN:
                continue
            hz_spread = (max(hz_y) - min(hz_y)) if len(hz_y) >= 2 else 0.0
            vt_spread = (max(vt_x) - min(vt_x)) if len(vt_x) >= 2 else 0.0
            _vlab = v_lab.get(gx, "?")
            _hlab = h_lab.get(gy, "?")
            out.append({
                "cx": gx, "cy": gy,
                "grid_cx": gx, "grid_cy": gy,
                "grid_ref": f"{_vlab}-{_hlab}",
                "n_frags": n, "span_w": round(sw, 1), "span_h": round(sh, 1),
            })
    for b in td.get("blocks", []):
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                txt = s["text"].strip()
                if _COL_TEXT_RE.match(txt):
                    tcx = (s["bbox"][0] + s["bbox"][2]) / 2.0
                    tcy = (s["bbox"][1] + s["bbox"][3]) / 2.0
                    if v_grid and h_grid:
                        nearest_gx = min(v_grid, key=lambda g: abs(tcx - g))
                        nearest_gy = min(h_grid, key=lambda g: abs(tcy - g))
                        if abs(tcx - nearest_gx) <= 60.0 and abs(tcy - nearest_gy) <= 60.0:
                            if not any(math.hypot(item["cx"] - nearest_gx, item["cy"] - nearest_gy) <= 25.0 for item in out):
                                _vlab = v_lab.get(nearest_gx, "?")
                                _hlab = h_lab.get(nearest_gy, "?")
                                out.append({
                                    "cx": nearest_gx, "cy": nearest_gy,
                                    "grid_cx": nearest_gx, "grid_cy": nearest_gy,
                                    "grid_ref": f"{_vlab}-{_hlab}",
                                    "n_frags": 4, "span_w": 12.0, "span_h": 12.0,
                                })
    # Final strict 1-to-1 deduplication of column candidates
    dedup_out = []
    for item in out:
        icx, icy = item["cx"], item["cy"]
        igx = item.get("grid_cx", icx)
        igy = item.get("grid_cy", icy)
        
        is_dup = False
        for existing in dedup_out:
            ecx, ecy = existing["cx"], existing["cy"]
            egx = existing.get("grid_cx", ecx)
            egy = existing.get("grid_cy", ecy)
            
            # Same grid intersection OR distance <= 45pt (~3.5ft)
            if (igx == egx and igy == egy) or math.hypot(icx - ecx, icy - ecy) <= 45.0:
                is_dup = True
                break
        if not is_dup:
            dedup_out.append(item)

    out = dedup_out
    print(f"[FOUNDATION] grid-anchored footings (deduplicated 1-to-1): {len(out)} "
          f"(grid {len(v_grid)}x{len(h_grid)}, R={R:.0f}pt)")
    return out


def filter_foundation_symbols_by_marks(symbols: list, page, v_grid: list, h_grid: list,
                                        is_foundation_plan: bool = False) -> list:
    """
    Reject candidate foundation-plan column/footing symbols that don't have a
    real mark label (F1, F1A, C2, P1, ...) anywhere near them -- shape-
    matching alone is too weak a signal on a cluttered real sheet (catches
    hatch-pattern fill lines, leader-line elbows, elevation callout text
    boxes, detail/section reference bubbles). Verified against two different
    real projects.

    Two things had to change from a naive "any mark within a fixed radius"
    filter, both found by testing against real drawings of very different
    density:

    1. RADIUS IS DERIVED FROM THE MARKS' OWN SPACING, not v_grid/h_grid.
       v_grid/h_grid (the general grid-line detector) turned out to be noisy
       on at least one real sheet -- it reported 19 "vertical grid lines"
       where only ~9 real column lines exist, which threw off any bay-width
       calculation built on top of it. The mark labels' own median nearest-
       neighbor spacing is a much more direct, reliable signal for "how
       dense is this sheet", since it's exactly the thing we're trying to
       calibrate against.
    2. EACH MARK CAN ONLY CLAIM A LIMITED NUMBER OF NEARBY SYMBOLS.
       A pure radius filter breaks down on dense sheets: when real marks are
       packed close together, nearly every point on the page ends up within
       reach of SOME real mark, so distance alone stops being selective
       (Congress Heights RC: 167 raw candidates, 77 real marks, but 136+
       still passed a radius-only filter). Capping how many candidates any
       single mark can "sponsor" (its nearest few, not everyone in range)
       keeps the filter selective on dense sheets while still tolerating
       sparse sheets where one type-label legitimately marks more than one
       physical column nearby.

    Calibrated against two real projects: Bayhealth Sussex MOB (sparse,
    ~224pt median mark spacing) and Congress Heights RC (dense, ~139pt).
    """
    if not (is_foundation_plan and symbols):
        return symbols

    # Tolerates real-world mark punctuation seen on live sheets: a trailing
    # comma from a "C4, BP1" style multi-mark callout ("C4," -> "C4"), and an
    # optional decimal suffix like "F7.0" for footing elevation marks. The
    # original exact-match pattern rejected both, which silently dropped
    # every interior column whose only nearby marks used this formatting
    # (interior columns get their type mark comma-separated from a footing/
    # base-plate mark, e.g. "C4, BP1"; perimeter columns happened to also
    # sit near cleanly-formatted pier marks like "P24" that passed, which is
    # why only the perimeter appeared to be marked at all).
    _MARK_RE = re.compile(r'^(?:[FPC]\d{1,3}(?:\.\d+)?[A-Z]?)$')
    _mark_positions: list[tuple[float, float]] = []
    try:
        for w in page.get_text("words"):
            word_text = (w[4] or "").strip().upper().rstrip(",;:")
            if _MARK_RE.match(word_text):
                _mark_positions.append(((w[0] + w[2]) / 2, (w[1] + w[3]) / 2))
    except Exception:
        _mark_positions = []

    if not _mark_positions:
        return symbols

    # Median nearest-OTHER-mark distance, ignoring <40pt gaps (those are the
    # same physical label split into two text-extraction tokens, e.g.
    # "F90" + "A", not two distinct marks).
    _nn_dists = []
    for i, (mx, my) in enumerate(_mark_positions):
        others = [math.hypot(mx - ox, my - oy)
                  for j, (ox, oy) in enumerate(_mark_positions) if j != i]
        others = sorted(d for d in others if d > 40.0)
        if others:
            _nn_dists.append(others[0])

    if _nn_dists:
        _nn_dists.sort()
        n = len(_nn_dists)
        _median_mark_spacing = (_nn_dists[n // 2] if n % 2
                                 else (_nn_dists[n // 2 - 1] + _nn_dists[n // 2]) / 2)
    else:
        _median_mark_spacing = 200.0  # only one mark on the whole page -- no spacing signal

    _MARK_RADIUS = _median_mark_spacing
    _CAP_PER_MARK = 2  # a mark may legitimately label more than one nearby
                        # column of the same type, but not an unlimited number

    accepted_idx: set = set()
    # Track each accepted symbol's OWN nearest mark distance (not just which
    # marks claimed it) so the Column Validation Engine downstream can score
    # "mark sitting right on the symbol" higher than "mark at the edge of
    # this sheet's tolerance" instead of treating every accepted symbol as
    # equally well-evidenced.
    nearest_mark_dist: dict = {}
    for mx, my in _mark_positions:
        dists = sorted(
            (math.hypot(s["cx"] - mx, s["cy"] - my), si)
            for si, s in enumerate(symbols)
            if math.hypot(s["cx"] - mx, s["cy"] - my) < _MARK_RADIUS
        )
        for _d, si in dists[:_CAP_PER_MARK]:
            accepted_idx.add(si)
            if si not in nearest_mark_dist or _d < nearest_mark_dist[si]:
                nearest_mark_dist[si] = _d

    filtered = []
    for si, s in enumerate(symbols):
        if si not in accepted_idx:
            continue
        s["nearest_mark_dist"] = round(nearest_mark_dist.get(si, _MARK_RADIUS), 1)
        s["mark_radius"] = round(_MARK_RADIUS, 1)
        filtered.append(s)

    print(f"[SYMBOLS] Mark-filter: median_mark_spacing={_median_mark_spacing:.0f} "
          f"radius={_MARK_RADIUS:.0f} cap={_CAP_PER_MARK} {len(symbols)} -> {len(filtered)}")
    return filtered


def detect_raster_grid_lines(img_path: str, plan_bounds: tuple) -> tuple:
    """
    Detect structural column grid lines from a raster image file.

    Uses morphological opening with long kernels:
      • Vertical kernel (height ≥ 40% of plan)  → isolates tall vertical lines
        → their X positions become v_grid
      • Horizontal kernel (width ≥ 40% of plan) → isolates wide horizontal lines
        → their Y positions become h_grid

    Structural column lines span the full plan height/width; beam centerlines,
    annotation lines, and other short marks are suppressed.
    """
    try:
        import cv2 as _cv2
        from PIL import Image as _PIL
    except ImportError:
        return [], []

    try:
        pil = _PIL.open(img_path).convert("RGB")
        img_arr = np.array(pil)
    except Exception:
        return [], []

    bx0, by0, bx1, by1 = [int(round(x)) for x in plan_bounds]
    bx0 = max(bx0, 0); by0 = max(by0, 0)
    bx1 = min(bx1, img_arr.shape[1]); by1 = min(by1, img_arr.shape[0])
    H = by1 - by0; W = bx1 - bx0
    if H < 50 or W < 50:
        return [], []

    region = img_arr[by0:by1, bx0:bx1]
    gray = _cv2.cvtColor(region, _cv2.COLOR_RGB2GRAY)
    # Invert: dark structural lines → white in binary
    _, binary = _cv2.threshold(gray, 200, 255, _cv2.THRESH_BINARY_INV)

    def _cluster_avg(vals: list, tol: float = 12.0) -> list:
        """Merge nearby positions by averaging each cluster."""
        if not vals:
            return []
        result = []
        group = [vals[0]]
        for v in sorted(vals)[1:]:
            if v - group[-1] <= tol:
                group.append(v)
            else:
                result.append(sum(group) / len(group))
                group = [v]
        result.append(sum(group) / len(group))
        return result

    # ── Vertical grid lines (column lines running top→bottom) ──────────────
    v_klen = max(30, int(H * 0.40))
    v_kernel = _cv2.getStructuringElement(_cv2.MORPH_RECT, (1, v_klen))
    v_img = _cv2.morphologyEx(binary, _cv2.MORPH_OPEN, v_kernel)
    v_sums = np.sum(v_img, axis=0).astype(float) / 255
    v_threshold = H * 0.25
    raw_vx = [float(x + bx0) for x in range(W) if v_sums[x] >= v_threshold]
    v_grid = _cluster_avg(raw_vx, tol=15)

    # ── Horizontal grid lines (row lines running left→right) ───────────────
    h_klen = max(30, int(W * 0.40))
    h_kernel = _cv2.getStructuringElement(_cv2.MORPH_RECT, (h_klen, 1))
    h_img = _cv2.morphologyEx(binary, _cv2.MORPH_OPEN, h_kernel)
    h_sums = np.sum(h_img, axis=1).astype(float) / 255
    h_threshold = W * 0.25
    raw_hy = [float(y + by0) for y in range(H) if h_sums[y] >= h_threshold]
    h_grid = _cluster_avg(raw_hy, tol=15)

    print(f"[RASTER_GRID] V({len(v_grid)}): {[round(x) for x in v_grid]}")
    print(f"[RASTER_GRID] H({len(h_grid)}): {[round(y) for y in h_grid]}")
    return v_grid, h_grid


def detect_beam_lines_raster(img_path: str, profiles: list,
                             plan_bounds: tuple,
                             span_v_grid: list = None,
                             span_h_grid: list = None) -> dict:
    """
    Raster equivalent of detect_beam_lines for vector PDFs.

    Uses actual drawn Hough line segments as span endpoints — each beam gets
    exactly the length of its drawn line in the image, just like vector PDF
    mode reads CAD geometry.

    Max-span cap is derived dynamically from the column-bay widths so that
    full-plan column-grid lines and sheet borders are always excluded.

    Returns { profile_idx: {"x1","y1","x2","y2","dir","length_pt"} }
    """
    try:
        import cv2 as _cv2
        from PIL import Image as _PIL
    except ImportError:
        return {}

    try:
        pil = _PIL.open(img_path).convert("L")
        img_gray = np.array(pil)
    except Exception:
        return {}

    bx0, by0, bx1, by1 = [int(round(x)) for x in plan_bounds]
    bx0 = max(bx0, 0); by0 = max(by0, 0)
    bx1 = min(bx1, img_gray.shape[1]); by1 = min(by1, img_gray.shape[0])
    plan_w = bx1 - bx0; plan_h = by1 - by0
    if plan_w < 50 or plan_h < 50:
        return {}

    # Derive dynamic max-span from bay widths so column/border lines are excluded.
    # Cap = 1.4× the widest detected structural bay (allows slight overrun).
    vg = span_v_grid or []
    hg = span_h_grid or []

    if len(vg) >= 2:
        max_bay_w = max(b - a for a, b in zip(sorted(vg), sorted(vg)[1:]))
        MAX_H = max_bay_w * 1.4
    else:
        MAX_H = plan_w * 0.45

    if len(hg) >= 2:
        max_bay_h = max(b - a for a, b in zip(sorted(hg), sorted(hg)[1:]))
        MAX_V = max_bay_h * 1.4
    else:
        MAX_V = plan_h * 0.45

    region = img_gray[by0:by1, bx0:bx1]
    edges = _cv2.Canny(region, threshold1=50, threshold2=150, apertureSize=3)
    raw = _cv2.HoughLinesP(
        edges,
        rho=1, theta=np.pi / 180,
        threshold=25,
        minLineLength=45,
        maxLineGap=6,          # small gap: don't bridge across column locations
    )
    if raw is None:
        return {}

    DIR_R   = 2.5
    LABEL_R = 60    # px — was 30; EasyOCR offset + Hough quantisation stacks to ~35 px;
                    # 60 px covers both error sources without jumping a full bay
    MIN_LEN = 45

    h_lines: list[tuple] = []   # (x1, y, x2, y, length)
    v_lines: list[tuple] = []   # (x, y1, x, y2, length)
    d_lines: list[tuple] = []   # (x1, y1, x2, y2, length)

    for seg in raw:
        x1r, y1r, x2r, y2r = seg[0]
        x1 = float(x1r + bx0); y1 = float(y1r + by0)
        x2 = float(x2r + bx0); y2 = float(y2r + by0)
        dx = abs(x2 - x1); dy = abs(y2 - y1)
        ln = math.hypot(dx, dy)
        if ln < MIN_LEN:
            continue
        if dx > dy * DIR_R and ln <= MAX_H:
            my = (y1 + y2) / 2
            h_lines.append((min(x1, x2), my, max(x1, x2), my, ln))
        elif dy > dx * DIR_R and ln <= MAX_V:
            mx = (x1 + x2) / 2
            v_lines.append((mx, min(y1, y2), mx, max(y1, y2), ln))
        else:
            if ln <= max(MAX_H, MAX_V):
                d_lines.append((x1, y1, x2, y2, ln))

    print(f"[RASTER_BEAM] MAX_H={MAX_H:.0f}px MAX_V={MAX_V:.0f}px  "
          f"H lines: {len(h_lines)}  V lines: {len(v_lines)}  D lines: {len(d_lines)}")

    result: dict = {}
    for p_idx, p in enumerate(profiles):
        pcx, pcy = p["cx"], p["cy"]
        best = None; best_d = float("inf"); best_dir = "H"

        # Prefer longer lines when equidistant (longer = more likely real beam)
        for (lx1, ly, lx2, _, ln) in h_lines:
            dy_l = abs(pcy - ly)
            if dy_l > LABEL_R:
                continue
            if pcx < lx1 - LABEL_R or pcx > lx2 + LABEL_R:
                continue
            score = dy_l - ln * 0.01   # slight length bonus
            if score < best_d:
                best_d = score
                best = (lx1, ly, lx2, ly, ln)
                best_dir = "H"

        for (lx, ly1, _, ly2, ln) in v_lines:
            dx_l = abs(pcx - lx)
            if dx_l > LABEL_R:
                continue
            if pcy < ly1 - LABEL_R or pcy > ly2 + LABEL_R:
                continue
            score = dx_l - ln * 0.01
            if score < best_d:
                best_d = score
                best = (lx, ly1, lx, ly2, ln)
                best_dir = "V"

        for (lx1, ly1, lx2, ly2, ln) in d_lines:
            # point-to-line distance
            den = math.hypot(lx2 - lx1, ly2 - ly1)
            num = abs((lx2 - lx1) * (ly1 - pcy) - (lx1 - pcx) * (ly2 - ly1))
            dist = num / den if den > 0 else float('inf')
            if dist > LABEL_R:
                continue
            # check if projection is within segment
            dot = ((pcx - lx1)*(lx2 - lx1) + (pcy - ly1)*(ly2 - ly1)) / (den*den) if den > 0 else -1
            if dot < -0.1 or dot > 1.1:
                continue
            score = dist - ln * 0.01
            if score < best_d:
                best_d = score
                best = (lx1, ly1, lx2, ly2, ln)
                best_dir = "D"

        if best:
            result[p_idx] = {
                "x1": best[0], "y1": best[1],
                "x2": best[2], "y2": best[3],
                "dir": best_dir,
                "length_pt": best[4],
            }

    print(f"[RASTER_BEAM] {len(result)}/{len(profiles)} profiles matched")
    return result


# ── Grid line extraction ──────────────────────────────────────────────────────
def extract_grid_lines(page, page_w, page_h, plan_bounds, text_dict=None):
    """
    Extract the X positions of vertical grid lines and the Y positions of
    horizontal grid lines from grid bubble label text.

    Orientation-agnostic strategy
    ─────────────────────────────
    Rather than assuming "letters are at top/bottom" or "numbers are at
    left/right" (which breaks on Calsteel-style drawings that put letters on
    the left and numbers at the top), we measure the SPREAD of each label
    family within the plan boundary:

      • If the label family spans more in X than in Y → the bubbles form a
        horizontal row at the top or bottom of the plan → they label VERTICAL
        grid lines → contribute their X positions to v_raw.

      • If the family spans more in Y than in X → the bubbles form a vertical
        column at the left or right → they label HORIZONTAL grid lines →
        contribute their Y positions to h_raw.

    This works correctly for both common layouts and any mixed-orientation plan.
    """
    bx0, by0, bx1, by1 = plan_bounds

    # Collect positions of each label family inside the plan boundary.
    #
    # We only trust labels that sit near the PERIMETER of the plan (outer 25%).
    # Grid bubbles are always at the top/bottom/left/right edge — never in the
    # interior.  Interior annotation numbers (joist loads "18K" OCR'd as "18",
    # span callouts "22", etc.) would otherwise pollute v_grid / h_grid and
    # make every beam span collapse to near-zero length.
    plan_w = max(bx1 - bx0, 1.0)
    plan_h = max(by1 - by0, 1.0)

    # ── Dynamic EDGE zone ────────────────────────────────────────────────────
    # Standard drawings: plan is 50-75% of page → EDGE=0.25 captures all
    # grid bubbles at the perimeter safely.
    #
    # Full-page drawings (Calsteel style, large hospitals): plan occupies
    # 90-100% of the page.  EDGE=0.25 only captures the outermost rows —
    # e.g. rows A-E and N-R of an A-R plan (18 rows), missing rows F-M.
    # Missing rows → wrong grid → wrong span fallback → chips in wrong place.
    #
    # Formula: EDGE scales from 0.25 (plan ≤ 70% of page) up to 0.45
    # (plan = full page).  This widens the capture zone for large plans
    # WITHOUT changing behaviour for standard-sized drawings.
    plan_cov = max((bx1 - bx0) / max(page_w, 1.0),
                   (by1 - by0) / max(page_h, 1.0))
    # Kicks in only when plan_cov > 0.70 to avoid widening on normal drawings
    EDGE = min(0.45, 0.25 + max(0.0, plan_cov - 0.70) * 0.67)

    # Each point now carries its actual bubble text alongside the position --
    # previously this text was read purely to classify letter-vs-number and
    # then thrown away, so every downstream consumer (registration.py's
    # multi-sheet grid persistence) had no real label to use and fell back to
    # sequential "1,2,3.../A,B,C" numbering that doesn't match the sheet's
    # real grid at all. Carrying (text, cx, cy) through lets us return the
    # REAL bubble label for each final position, not just its coordinate.
    letter_pts: list[tuple[str, float, float]] = []
    number_pts: list[tuple[str, float, float]] = []
    # Decimal sub-grid candidates (e.g. "D.1", "3.1") that matched the label
    # regex and every other gate EXCEPT near_edge, kept aside so a later
    # additive pass can recover the ones printed on an interior rail rather
    # than the sheet's outer margin -- see _absorb_interior_subgrids below
    # for why that recovery is needed and why it's safe to only ever add,
    # never replace, a position here.
    letter_interior_candidates: list[tuple[str, float, float]] = []
    number_interior_candidates: list[tuple[str, float, float]] = []

    _td = text_dict if text_dict is not None else page.get_text("dict")
    for block in _td["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t  = span["text"].strip()
                fs = span.get("size", 10)
                # Require minimum legible font size for grid bubbles.
                # Interior dimension annotations are typically drawn at < 7 pt;
                # grid bubble text is always ≥ 7 pt (must be readable on plot).
                if not t or len(t) > 5 or fs < 7:
                    continue
                cx = (span["bbox"][0] + span["bbox"][2]) / 2
                cy = (span["bbox"][1] + span["bbox"][3]) / 2
                # Must be inside (or very close to) the plan boundary
                if not (bx0 - 60 <= cx <= bx1 + 60 and
                        by0 - 60 <= cy <= by1 + 60):
                    continue
                # Decimal sub-grid labels are captured as interior-recovery
                # candidates UNCONDITIONALLY, before the near_edge test --
                # not only when near_edge fails. A sub-grid on its own
                # interior rail is very often just as far from the raw
                # page's edge test as a perimeter bubble happens to be (the
                # near_edge test alone doesn't reliably separate them), but
                # it still gets dropped a stage later by the dominant-band /
                # monotonic / dominant-sequence filters below because it
                # sits far from the main row's band -- capturing it here,
                # before any of those filters run, is what lets the
                # absorption pass after them recover it regardless of which
                # stage actually excluded it.
                if "." in t:
                    if _GRID_LETTER.match(t):
                        letter_interior_candidates.append((t, cx, cy))
                    elif _GRID_NUMBER.match(t):
                        try:
                            if 0.5 <= float(t) <= 200:
                                number_interior_candidates.append((t, cx, cy))
                        except ValueError:
                            pass

                # Must be near the perimeter — grid bubbles are always at the edge
                near_edge = (
                    cx < bx0 + plan_w * EDGE or cx > bx1 - plan_w * EDGE or
                    cy < by0 + plan_h * EDGE or cy > by1 - plan_h * EDGE
                )
                if not near_edge:
                    continue

                if _GRID_LETTER.match(t):
                    letter_pts.append((t, cx, cy))
                elif _GRID_NUMBER.match(t):
                    try:
                        if not (0.5 <= float(t) <= 200):
                            continue
                    except ValueError:
                        continue
                    number_pts.append((t, cx, cy))

    # ── Dominant-band noise filter ──────────────────────────────────────────
    # ROOT CAUSE (found on full-page / high-coverage drawings such as this
    # project's binder, where plan_cov -> 1.0 and EDGE widens to its max of
    # 0.45): a 0.45 EDGE zone covers the outer 45% on EACH side, i.e. ~90% of
    # the page along that axis. That leaves almost no "interior" region to
    # exclude, so interior dimension strings, joist-spacing call-outs, and
    # load-schedule figures (e.g. "27", "30" PSF values) scattered anywhere
    # in that 90% band pass the perimeter check and get treated as grid
    # bubbles. On a real sheet this pollutes the candidate set ~10x over the
    # true bubble count (e.g. 190 "number" candidates on a sheet with only
    # 21 real grid numbers) — far past the 55%-majority threshold that
    # _dominant_sequence() needs to reject noise, so the noise survives.
    #
    # Real grid bubbles for one axis always sit on a single shared row (same
    # Y, letters/numbers spread out in X) or a single shared column (same X,
    # spread out in Y) — because they're printed along ONE edge of the plan.
    # Interior annotations don't share that coordinate; each one sits at its
    # own essentially-unique X/Y. So before classifying letters vs numbers
    # into vertical/horizontal families, snap each point set to whichever
    # single coordinate band actually holds the bulk of the points (its
    # "printed edge"), and drop everything that isn't part of that band (or
    # a comparably-sized twin band — many drawings repeat the same grid
    # labels on both the near and far edge of the plan).
    #
    # This is a tighter, position-based test layered on top of (not instead
    # of) the existing EDGE/perimeter/font-size/numeric-range checks above —
    # none of those are weakened.
    def _dominant_band(pts, tol=15.0, min_frac=0.45, min_count=3):
        if len(pts) < min_count:
            return pts

        def _bucket(idx):
            buckets: dict[int, list] = {}
            for p in pts:
                key = round(p[idx] / tol)
                buckets.setdefault(key, []).append(p)
            return buckets

        buckets_x = _bucket(1)   # points sharing near-identical cx (a column)
        buckets_y = _bucket(2)   # points sharing near-identical cy (a row)
        best_x = max(buckets_x.values(), key=len)
        best_y = max(buckets_y.values(), key=len)

        # Pick whichever axis actually concentrates the points into a real
        # band (real grid bubbles cluster tightly on ONE of these two axes;
        # noise doesn't cluster tightly on either).
        if len(best_x) >= len(best_y):
            buckets, best, axis_idx, lo, hi, span = buckets_x, best_x, 1, bx0, bx1, plan_w
        else:
            buckets, best, axis_idx, lo, hi, span = buckets_y, best_y, 2, by0, by1, plan_h

        threshold = max(min_count, min_frac * len(best))
        candidate_groups = [grp for grp in buckets.values() if len(grp) >= threshold]

        # Band SIZE alone isn't enough to pick the real grid-bubble row: on
        # a dense framing/roof plan, a repeated per-bay callout (joist
        # spacing, deck gauge, etc.) prints once per bay just like grid
        # labels do, and can easily out-number the true bubble row (found
        # live on a roof framing sheet: a joist-spacing row of 14 numbers
        # at mid-sheet beat the real 12-number grid-label row printed at
        # the true top edge, so the old "biggest band wins" rule kept the
        # noise and dropped the real grid entirely -- V grid came back
        # empty on a sheet where the bubbles were clearly visible).
        # Real grid bubbles are always printed AT the plan's actual edge;
        # an interior per-bay callout is not, no matter how many times it
        # repeats. Prefer whichever candidate band(s) sit within the outer
        # 15% of the plan on this axis (checking both edges, since some
        # sheets label both the near and far side) over one that's merely
        # bigger but sits deeper inside the plan.
        EDGE_MARGIN = 0.35 * span
        edge_groups = [
            grp for grp in candidate_groups
            if (sum(p[axis_idx] for p in grp) / len(grp)) <= lo + EDGE_MARGIN
            or (sum(p[axis_idx] for p in grp) / len(grp)) >= hi - EDGE_MARGIN
        ]
        kept = [p for grp in (edge_groups or candidate_groups) for p in grp]
        # Never let the filter manufacture a false "no grid" result when the
        # raw candidate set was small to begin with and simply didn't form a
        # clean single band — fall back to returning everything untouched
        # rather than guessing wrong.
        return kept if kept else pts

    def _label_rank(label):
        """Numeric rank for a grid label, used only to test ordering — NOT
        for the returned position/label data itself."""
        try:
            return float(label)
        except ValueError:
            mm = re.match(r"^([A-Z])\1?(?:\.(\d+))?", label)
            if not mm:
                return 0.0
            base = ord(mm.group(1))
            sub = float(mm.group(2)) if mm.group(2) else 0.0
            return base * 100 + sub

    def _monotonic_filter(pts, min_frac=0.75):
        """
        Reject point sets that pass the band-density test above but are NOT
        actually a grid: e.g. a printed load/area schedule table can have a
        tight column of numbers (tripping the band filter) whose VALUES
        don't track position — real grid bubbles are always laid out in
        ascending (or descending) order along the edge they're printed on.
        Groups points by band (columns vs rows) and evaluates monotonicity
        along that band's variation axis (Y for columns, X for rows).
        """
        if len(pts) < 3:
            return pts
        cols: dict[int, list] = {}
        for p in pts:
            cols.setdefault(round(p[1] / 60.0), []).append(p)
        rows: dict[int, list] = {}
        for p in pts:
            rows.setdefault(round(p[2] / 60.0), []).append(p)
        
        max_col_size = max((len(c) for c in cols.values()), default=0)
        max_row_size = max((len(r) for r in rows.values()), default=0)
        
        kept = []
        if max_col_size >= max_row_size:
            for col_pts in cols.values():
                if len(col_pts) < 3:
                    kept.extend(col_pts)
                    continue
                sp = sorted(col_pts, key=lambda p: p[2])
                vals = [_label_rank(p[0]) for p in sp]
                n = len(vals) - 1
                inc = sum(1 for i in range(n) if vals[i + 1] >= vals[i])
                dec = sum(1 for i in range(n) if vals[i + 1] <= vals[i])
                if max(inc, dec) / n >= min_frac:
                    kept.extend(col_pts)
        else:
            for row_pts in rows.values():
                if len(row_pts) < 3:
                    kept.extend(row_pts)
                    continue
                sp = sorted(row_pts, key=lambda p: p[1])
                vals = [_label_rank(p[0]) for p in sp]
                n = len(vals) - 1
                inc = sum(1 for i in range(n) if vals[i + 1] >= vals[i])
                dec = sum(1 for i in range(n) if vals[i + 1] <= vals[i])
                if max(inc, dec) / n >= min_frac:
                    kept.extend(row_pts)
        return kept if kept else pts

    letter_pts = _monotonic_filter(_dominant_band(letter_pts))
    number_pts = _monotonic_filter(_dominant_band(number_pts))

    def _classify_family(pts):
        """Return (v_points, h_points) for a set of (label, cx, cy) bubble points."""
        if not pts:
            return [], []
        xs = [p[1] for p in pts]
        ys = [p[2] for p in pts]
        def _uniq(vals, tol=20):
            seen = []
            for v in sorted(vals):
                if not seen or abs(v - seen[-1]) > tol:
                    seen.append(v)
            return len(seen)
        if _uniq(xs) >= _uniq(ys):
            return pts, []
        else:
            return [], pts

    def _dominant_sequence(pts, span):
        """
        Universal interior-annotation filter, operating on (label, cx, cy)
        points keyed by their relevant axis coordinate (already isolated by
        _classify_family into an all-V or all-H family).

        With a wider EDGE zone (needed for large/full-page plans), some
        interior annotation numbers (bay-span callouts like '18', '24')
        can enter the candidate set alongside real grid bubble labels.

        Real grid bubbles form a single CONTINUOUS sequence across the full
        plan span — no large gaps between them.  Interior annotation clusters
        sit at isolated positions separated from the main grid by large empty
        stretches.

        Algorithm: find the longest group of positions where consecutive
        entries are ≤ max_gap apart.  Return that group if it accounts for
        ≥ 55% of total candidates (i.e. real grid dominates); otherwise
        return all values unchanged (sparse / irregular grid, no filtering).

        max_gap = max(30% of plan span, 120 pt) — generous enough to handle
        any structural bay size (typical largest bay ≤ 30 ft = 270–405 pt).
        """
        if len(pts) < 3:
            return pts
        # Sort by whichever coordinate actually varies for this family (the
        # axis value lives in cx for a V family, cy for an H family -- both
        # are present on every point, so just pick by spread).
        xs_spread = max(p[1] for p in pts) - min(p[1] for p in pts)
        ys_spread = max(p[2] for p in pts) - min(p[2] for p in pts)
        axis_idx = 1 if xs_spread >= ys_spread else 2

        sv      = sorted(pts, key=lambda p: p[axis_idx])
        max_gap = max(span * 0.30, 120.0)

        best, cur = [sv[0]], [sv[0]]
        for p in sv[1:]:
            if p[axis_idx] - cur[-1][axis_idx] <= max_gap:
                cur.append(p)
            else:
                if len(cur) > len(best):
                    best = cur[:]
                cur = [p]
        if len(cur) > len(best):
            best = cur

        # Only apply if the dominant sequence is clearly the majority.
        # For truly sparse grids (large irregular bays) the condition won't
        # fire and all values are returned untouched.
        return best if len(best) >= max(3, len(pts) * 0.55) else pts

    lv, lh = _classify_family(letter_pts)
    nv, nh = _classify_family(number_pts)

    v_pts = lv + nv
    h_pts = lh + nh

    # Apply dominant-sequence filter to drop isolated annotation clusters
    # that sneak in when EDGE is widened for large / full-page drawings.
    v_pts = _dominant_sequence(v_pts, plan_w)
    h_pts = _dominant_sequence(h_pts, plan_h)

    def dedup_labeled(pts, axis_idx, tol=18):
        """Dedup by position (same clustering as before), keeping the first
        real label text seen in each cluster."""
        out_pos: list[float] = []
        out_label: dict[float, str] = {}
        for p in sorted(pts, key=lambda p: p[axis_idx]):
            v = p[axis_idx]
            if not out_pos or abs(v - out_pos[-1]) > tol:
                out_pos.append(v)
                out_label[v] = p[0]
        return out_pos, out_label

    v_grid, v_labels = dedup_labeled(v_pts, 1)
    h_grid, h_labels = dedup_labeled(h_pts, 2)

    def _absorb_interior_subgrids(grid, labels, candidates, axis_idx, tol=18):
        """
        Recover decimal sub-grid bubbles (e.g. "D.1", "D.9") excluded above
        purely because they're printed on an INTERIOR rail rather than the
        sheet's outer margin -- on a stepped or L-shaped building, the
        sub-grids serving the step are routinely dimensioned on their own
        interior line instead of at the plan edge, exactly the case
        app/engineering/grid_geometry_pass.py's own _absorb_interior_grids
        already recovers for the dimension-line overlay. THIS array
        (v_grid/h_grid) feeds a separate, older pass used for column-to-grid
        labeling ("Col @ X-Y"), and until now had no equivalent recovery --
        so a real column sitting in that interior area had no correct grid
        line to snap to and produced a mismatched-looking reference instead.

        Purely additive: a candidate is only admitted when its own base
        letter/number is ALREADY a confirmed grid on this axis (so it can't
        introduce a family that failed every other check above) and its
        position falls strictly between two already-confirmed neighbouring
        grid coordinates, never on top of one and never past either end --
        both of which are true for a real sub-grid and essentially never
        true for noise (a stray callout, a schedule reference) that merely
        happens to share the decimal-label shape.
        """
        if not grid or not candidates:
            return grid, labels
        existing = set(labels.values())
        sorted_grid = sorted(grid)
        for text, cx, cy in candidates:
            if text in existing:
                continue
            base = text.split(".")[0]
            if base not in existing:
                continue  # its own family was never confirmed -- not safe to trust
            pos = cx if axis_idx == 1 else cy
            lo = max((g for g in sorted_grid if g < pos - tol), default=None)
            hi = min((g for g in sorted_grid if g > pos + tol), default=None)
            if lo is None or hi is None:
                continue  # must sit strictly between two confirmed grids, not past either end
            if any(abs(pos - g) <= tol for g in sorted_grid):
                continue  # effectively on top of an existing grid -- not a new one
            grid.append(pos)
            labels[pos] = text
            existing.add(text)
        grid.sort()
        return grid, labels

    v_grid, v_labels = _absorb_interior_subgrids(v_grid, v_labels, letter_interior_candidates + number_interior_candidates, 1)
    h_grid, h_labels = _absorb_interior_subgrids(h_grid, h_labels, letter_interior_candidates + number_interior_candidates, 2)

    print(f"[GRID] V({len(v_grid)}): {[(round(x), v_labels[x]) for x in v_grid]}")
    print(f"[GRID] H({len(h_grid)}): {[(round(y), h_labels[y]) for y in h_grid]}")
    return v_grid, h_grid, v_labels, h_labels


# ── Grid Dimension Extraction ──────────────────────────────────────────────────
def parse_dimension_string(s: str) -> float | None:
    """Parse an architectural dimension string (e.g. 31'-4", 31'-4 1/2", 216'-0 5/8", 20', 16") into decimal feet."""
    if not s:
        return None
    s = s.strip()
    m = re.search(r"(\d+)\s*['’](?:\s*[-–]\s*(\d+(?:\s+\d+/\d+|\.\d+|/\d+)?)\s*[\"”]?)?", s)
    if not m:
        m2 = re.search(r"^(\d+(?:\s+\d+/\d+)?)\s*[\"”]$", s)
        if m2:
            val_str = m2.group(1)
            if '/' in val_str:
                parts = val_str.split()
                if len(parts) == 2:
                    whole = float(parts[0])
                    num, den = map(float, parts[1].split('/'))
                    return (whole + num/den) / 12.0
                elif len(parts) == 1:
                    num, den = map(float, parts[0].split('/'))
                    return (num/den) / 12.0
            return float(val_str) / 12.0
        return None
    
    feet = float(m.group(1))
    inch_part = m.group(2)
    if not inch_part:
        return feet
    inch_part = inch_part.strip()
    if ' ' in inch_part:
        w, frac = inch_part.split(' ', 1)
        whole = float(w)
        num, den = map(float, frac.split('/'))
        return feet + (whole + num/den) / 12.0
    elif '/' in inch_part:
        num, den = map(float, inch_part.split('/'))
        return feet + (num/den) / 12.0
    else:
        return feet + float(inch_part) / 12.0


def ft_to_arch_str(ft_val: float) -> str:
    """Convert decimal feet to architectural feet-inches string (e.g. 31.33 -> 31'-4")."""
    feet = int(ft_val)
    inches = (ft_val - feet) * 12.0
    int_inches = int(round(inches))
    if int_inches == 12:
        feet += 1
        int_inches = 0
    return f"{feet}'-{int_inches}\""


_IGNORE_DIM_PREFIXES = ("T.O.S", "TOC", "T.O.", "EL.", "ELEV", "SCALE", "FINISH", "DETAIL", "SECTION", "#", "REBAR", "BAR", "DECK", "CONC")

def is_valid_dim_text(text: str) -> bool:
    """Check if text span is a valid architectural dimension (e.g. 31'-4", 33'-0", 12'-0 5/8", 10", 2'-3 5/8")."""
    t = text.strip().upper()
    if any(t.startswith(p) or p in t for p in _IGNORE_DIM_PREFIXES):
        return False
    if re.match(r"^\d+\s*['’]", t) or re.match(r"^\d+(?:/\d+|\s+\d+/\d+)?\s*[\"”]$", t):
        return True
    return False


def extract_grid_dimensions(page, page_w: float, page_h: float, plan_bounds: tuple,
                            v_grid: list, h_grid: list,
                            v_labels: dict, h_labels: dict,
                            pts_per_foot: float, text_dict: dict = None,
                            is_explicit_scale: bool = True) -> list[dict]:
    """
    Extract clean, non-overlapping consecutive grid-to-grid bay dimension lines and outer total lines.
    - Consecutive bay chain along the inner track (every bay: A-A.5, A.5-B, B-B.2, B.2-B.3, B.3-B.6...)
    - Full building total dimension along the outer track (A-D TOTAL, 1-7.2 TOTAL)
    - Zero duplicate overlapping lines, exact grid bubble snap.
    """
    if not v_grid and not h_grid:
        return []
    
    ppf = pts_per_foot if (pts_per_foot and pts_per_foot > 0) else 9.0
    td = text_dict or page.get_text("dict")
    scale_source = "explicit" if is_explicit_scale else "guessed"
    
    # 1. Collect all dimension text spans across the drawing
    dim_spans: list[dict] = []
    for b in td.get("blocks", []):
        for l in b.get("lines", []):
            for sp in l.get("spans", []):
                t = sp.get("text", "").strip()
                if not is_valid_dim_text(t):
                    continue
                val = parse_dimension_string(t)
                if val is not None and 0.5 <= val <= 350.0:
                    cx = (sp["bbox"][0] + sp["bbox"][2]) / 2
                    cy = (sp["bbox"][1] + sp["bbox"][3]) / 2
                    dim_spans.append({
                        "text": t,
                        "val_ft": val,
                        "cx": cx,
                        "cy": cy,
                        "bbox": sp["bbox"]
                    })
    
    results: list[dict] = []
    sorted_v = sorted(set(v_grid)) if v_grid else []
    sorted_h = sorted(set(h_grid)) if h_grid else []
    
    min_h = min(h_grid) if h_grid else (plan_bounds[1] if plan_bounds else page_h * 0.2)
    max_h = max(h_grid) if h_grid else (plan_bounds[3] if plan_bounds else page_h * 0.8)
    min_v = min(v_grid) if v_grid else (plan_bounds[0] if plan_bounds else page_w * 0.2)
    max_v = max(v_grid) if v_grid else (plan_bounds[2] if plan_bounds else page_w * 0.8)
    
    # Extract raw bubble points per margin using physical coordinate alignment to actual grid lines
    all_bubbles_raw = []
    for b in td.get("blocks", []):
        for l in b.get("lines", []):
            for sp in l.get("spans", []):
                t = sp.get("text", "").strip()
                bbox = sp.get("bbox", [])
                cx = (bbox[0] + bbox[2]) / 2
                cy = (bbox[1] + bbox[3]) / 2
                if _GRID_LETTER.match(t) or _GRID_NUMBER.match(t):
                    all_bubbles_raw.append((t, cx, cy))

    v_bubbles_raw = [b for b in all_bubbles_raw if any(abs(b[1] - vx) <= 25.0 for vx in sorted_v)]
    h_bubbles_raw = [b for b in all_bubbles_raw if any(abs(b[2] - hy) <= 25.0 for hy in sorted_h)]

    # ── 1. Vertical Grid Lines (Horizontal Top & Bottom Tracks) ─────────────────
    def _extract_side_band(b_list, is_x_axis=True):
        if not b_list:
            return []
        coord_idx = 1 if is_x_axis else 2
        var_idx = 2 if is_x_axis else 1
        buckets = {}
        for b in b_list:
            key = round(b[coord_idx] / 10.0) * 10.0
            buckets.setdefault(key, []).append(b)
        best_bucket = max(buckets.values(), key=len) if buckets else []
        if len(best_bucket) >= 3:
            return sorted(best_bucket, key=lambda b: b[var_idx])
        return []

    top_band_raw = _extract_side_band([b for b in all_bubbles_raw if b[2] < page_h * 0.35 and any(abs(b[1] - vx) <= 25.0 for vx in sorted_v)], is_x_axis=False)
    bot_band_raw = _extract_side_band([b for b in all_bubbles_raw if b[2] > page_h * 0.65 and any(abs(b[1] - vx) <= 25.0 for vx in sorted_v)], is_x_axis=False)
    left_band_raw = _extract_side_band([b for b in all_bubbles_raw if b[1] < page_w * 0.35 and any(abs(b[2] - hy) <= 25.0 for hy in sorted_h)], is_x_axis=True)
    right_band_raw = _extract_side_band([b for b in all_bubbles_raw if b[1] > page_w * 0.65 and any(abs(b[2] - hy) <= 25.0 for hy in sorted_h)], is_x_axis=True)

    top_v_grids = [b[1] for b in top_band_raw] if top_band_raw else sorted_v
    top_v_labels = {b[1]: b[0] for b in top_band_raw} if top_band_raw else v_labels
    bot_v_grids = [b[1] for b in bot_band_raw] if bot_band_raw else sorted_v
    bot_v_labels = {b[1]: b[0] for b in bot_band_raw} if bot_band_raw else v_labels

    left_h_grids = [b[2] for b in left_band_raw] if left_band_raw else sorted_h
    left_h_labels = {b[2]: b[0] for b in left_band_raw} if left_band_raw else h_labels
    right_h_grids = [b[2] for b in right_band_raw] if right_band_raw else sorted_h
    right_h_labels = {b[2]: b[0] for b in right_band_raw} if right_band_raw else h_labels

    def _find_validated_tracks(cands, grid_coords, is_horizontal_track=True):
        if len(cands) < 2:
            return []
        buckets: dict[float, list] = {}
        for ds in cands:
            pos = ds["cy"] if is_horizontal_track else ds["cx"]
            key = round(pos / 20.0) * 20.0
            buckets.setdefault(key, []).append(ds)
        
        scored_tracks = []
        for track_pos, bucket_cands in buckets.items():
            if len(bucket_cands) < 2:
                continue
            matching_spans = []
            for dt in bucket_cands:
                p_coord = dt["cx"] if is_horizontal_track else dt["cy"]
                dim_val = dt["val_ft"]
                for i in range(len(grid_coords) - 1):
                    g1 = grid_coords[i]
                    g2 = grid_coords[i+1]
                    if g1 - 25.0 <= p_coord <= g2 + 25.0:
                        calc_ft = abs(g2 - g1) / ppf
                        err = abs(dim_val - calc_ft)
                        tol = max(2.0, calc_ft * 0.18)
                        if err <= tol:
                            matching_spans.append((dt, g1, g2, calc_ft, err))
                            break
            if len(matching_spans) >= 2 or (len(bucket_cands) >= 3 and len(matching_spans) >= 1):
                scored_tracks.append((len(matching_spans), len(bucket_cands), track_pos, bucket_cands))
        
        if not scored_tracks:
            return []
        # Return only the single highest-scoring, cleanest track for this margin
        scored_tracks.sort(key=lambda t: (t[0], t[1]), reverse=True)
        best = scored_tracks[0]
        return [(best[3], best[2])]

    if len(sorted_v) >= 2:
        top_cands = [ds for ds in dim_spans if ds["cy"] < min_h + 30.0 and min_v - 60 <= ds["cx"] <= max_v + 60]
        bot_cands = [ds for ds in dim_spans if ds["cy"] > max_h - 30.0 and min_v - 60 <= ds["cx"] <= max_v + 60]
        
        track_y_list = [
            (cands, tpos, top_v_grids, top_v_labels)
            for cands, tpos in _find_validated_tracks(top_cands, top_v_grids, is_horizontal_track=True)
        ] + [
            (cands, tpos, bot_v_grids, bot_v_labels)
            for cands, tpos in _find_validated_tracks(bot_cands, bot_v_grids, is_horizontal_track=True)
        ]
            
        for side_cands, track_y, side_grids, side_labels in track_y_list:
            for i in range(len(side_grids) - 1):
                vx1 = side_grids[i]
                vx2 = side_grids[i+1]
                dist_pt = vx2 - vx1
                if dist_pt < 2.0:
                    continue
                
                calc_ft = round(dist_pt / ppf, 2)
                final_ft = calc_ft
                final_text = ft_to_arch_str(calc_ft)
                
                fl = side_labels.get(vx1, str(i+1))
                tl = side_labels.get(vx2, str(i+2))
                
                matched_ocr = None
                best_diff = min(2.0, max(0.5, calc_ft * 0.15))
                for dt in side_cands:
                    if vx1 - 15.0 <= dt["cx"] <= vx2 + 15.0:
                        diff = abs(dt["val_ft"] - calc_ft)
                        if diff < best_diff:
                            best_diff = diff
                            matched_ocr = dt
                
                results.append({
                    "id": f"dim_v_{fl}_{tl}_{round(track_y)}",
                    "axis": "V",
                    "from_grid": str(fl),
                    "to_grid": str(tl),
                    "label": f"{fl}–{tl}",
                    "length_ft": final_ft,
                    "text": final_text,
                    "x1": round(vx1 / page_w, 4),
                    "y1": round(track_y / page_h, 4),
                    "x2": round(vx2 / page_w, 4),
                    "y2": round(track_y / page_h, 4),
                    "source": "scale_verified" if matched_ocr else "scale_computed",
                    "ocr_text": matched_ocr["text"] if matched_ocr else None,
                    "scale_source": scale_source
                })
                
            # Overall Total Width Dimension
            total_v_dist = side_grids[-1] - side_grids[0]
            total_v_ft = round(total_v_dist / ppf, 2)
            first_v = side_labels.get(side_grids[0], "1")
            last_v = side_labels.get(side_grids[-1], str(len(side_grids)))
            tot_y = track_y - 25.0 if track_y < page_h * 0.5 else track_y + 25.0
            
            matched_tot = None
            for dt in side_cands:
                if abs(dt["val_ft"] - total_v_ft) <= 3.0:
                    matched_tot = dt
                    tot_y = dt["cy"]
                    break
                    
            results.append({
                "id": f"dim_v_total_{first_v}_{last_v}_{round(tot_y)}",
                "axis": "V",
                "from_grid": str(first_v),
                "to_grid": str(last_v),
                "label": f"{first_v}–{last_v} (TOTAL)",
                "length_ft": total_v_ft,
                "text": ft_to_arch_str(total_v_ft),
                "x1": round(side_grids[0] / page_w, 4),
                "y1": round(tot_y / page_h, 4),
                "x2": round(side_grids[-1] / page_w, 4),
                "y2": round(tot_y / page_h, 4),
                "source": "scale_verified" if matched_tot else "scale_computed",
                "ocr_text": matched_tot["text"] if matched_tot else None,
                "scale_source": scale_source
            })

    # ── 2. Horizontal Grid Lines (Vertical Left & Right Tracks) ─────────────────
    if len(sorted_h) >= 2:
        left_cands = [ds for ds in dim_spans if ds["cx"] < min_v + 40.0 and min_h - 60 <= ds["cy"] <= max_h + 60]
        right_cands = [ds for ds in dim_spans if ds["cx"] > max_v - 40.0 and min_h - 60 <= ds["cy"] <= max_h + 60]
        
        track_x_list = [
            (cands, tpos, left_h_grids, left_h_labels)
            for cands, tpos in _find_validated_tracks(left_cands, left_h_grids, is_horizontal_track=False)
        ] + [
            (cands, tpos, right_h_grids, right_h_labels)
            for cands, tpos in _find_validated_tracks(right_cands, right_h_grids, is_horizontal_track=False)
        ]
            
        for side_cands, track_x, side_grids, side_labels in track_x_list:
            for j in range(len(side_grids) - 1):
                hy1 = side_grids[j]
                hy2 = side_grids[j+1]
                dist_pt = hy2 - hy1
                if dist_pt < 2.0:
                    continue
                
                # 100% Pure scale computation — zero OCR text overriding
                calc_ft = round(dist_pt / ppf, 2)
                final_ft = calc_ft
                final_text = ft_to_arch_str(calc_ft)
                
                fl = side_labels.get(hy1, chr(65 + j))
                tl = side_labels.get(hy2, chr(65 + j + 1))
                
                matched_ocr = None
                best_diff = min(2.0, max(0.5, calc_ft * 0.15))
                for dt in side_cands:
                    if hy1 - 15.0 <= dt["cy"] <= hy2 + 15.0:
                        diff = abs(dt["val_ft"] - calc_ft)
                        if diff < best_diff:
                            best_diff = diff
                            matched_ocr = dt
                
                results.append({
                    "id": f"dim_h_{fl}_{tl}_{round(track_x)}",
                    "axis": "H",
                    "from_grid": str(fl),
                    "to_grid": str(tl),
                    "label": f"{fl}–{tl}",
                    "length_ft": final_ft,
                    "text": final_text,
                    "x1": round(track_x / page_w, 4),
                    "y1": round(hy1 / page_h, 4),
                    "x2": round(track_x / page_w, 4),
                    "y2": round(hy2 / page_h, 4),
                    "source": "scale_verified" if matched_ocr else "scale_computed",
                    "ocr_text": matched_ocr["text"] if matched_ocr else None,
                    "scale_source": scale_source
                })
                
            # Overall Total Height Dimension
            total_h_dist = side_grids[-1] - side_grids[0]
            total_h_ft = round(total_h_dist / ppf, 2)
            first_h = side_labels.get(side_grids[0], "A")
            last_h = side_labels.get(side_grids[-1], "D")
            tot_x = track_x + 30.0 if track_x > page_w * 0.5 else track_x - 30.0
            
            matched_tot_h = None
            for dt in side_cands:
                if abs(dt["val_ft"] - total_h_ft) <= 3.0:
                    matched_tot_h = dt
                    tot_x = dt["cx"]
                    break
                    
            results.append({
                "id": f"dim_h_total_{first_h}_{last_h}_{round(tot_x)}",
                "axis": "H",
                "from_grid": str(first_h),
                "to_grid": str(last_h),
                "label": f"{first_h}–{last_h} (TOTAL)",
                "length_ft": total_h_ft,
                "text": ft_to_arch_str(total_h_ft),
                "x1": round(tot_x / page_w, 4),
                "y1": round(side_grids[0] / page_h, 4),
                "x2": round(tot_x / page_w, 4),
                "y2": round(side_grids[-1] / page_h, 4),
                "source": "scale_verified" if matched_tot_h else "scale_computed",
                "ocr_text": matched_tot_h["text"] if matched_tot_h else None,
                "scale_source": scale_source
            })

    return results


# ── Member classification ─────────────────────────────────────────────────────
def classify_member(profile: str,
                    cx: float = 0, cy: float = 0,
                    column_symbols: list = None,
                    v_grid: list = None,
                    h_grid: list = None,
                    is_girt: bool = False) -> str:
    """
    Classify a steel section label as column / beam / brace.

    Works for ANY drawing — ordered from most reliable to least:

      TIER 0  Profile type   PIPE, square HSS → always column
      TIER 1  Symbol nearby  I/H mark detected close to this label
      TIER 2  Grid cross     label sits near a named grid intersection
      TIER 3  Depth rule     W6/W8/W10 are almost always columns in practice
      TIER 4  Weight rule    heavy section for its depth → column

    Keeping TIER 3 (depth rule) separate ensures short W-sections are caught
    even on drawings where symbol detection or grid detection yields nothing.
    """
    if not profile or profile == "?":
        return "beam"
    p = str(profile or "").upper().strip()

    # ── SJI Steel Joist sections (K, LH, DLH, JG, KSP, CS) ────────────────────
    if (re.match(r'^\d{1,2}K\d+$', p) or
        re.match(r'^\d{1,2}(?:LH|DLH)\d+$', p) or
        re.match(r'^\d{1,2}KSP$', p) or
        re.match(r'^\d{1,2}G\d+N', p) or
        re.match(r'^\d{1,2}(?:CJ|CS)\d+$', p)):
        return "joist"

    # ── Angle / brace sections ────────────────────────────────────────────────
    if re.match(r'ISA', p) or re.match(r'L\d', p):
        return "brace"

    # ── TIER 0 — Profile type: always a column regardless of drawing ──────────
    if re.match(r'PIPE', p):
        return "column"

    hss = re.match(r'HSS([\d.]+)[Xx]([\d.]+)', p)
    if hss:
        try:
            d1 = float(hss.group(1))
            d2 = float(hss.group(2))
            # A GIRT is by definition a horizontal secondary framing member --
            # never a column -- regardless of the HSS being square in section.
            # Without this, square HSS girts (e.g. "HSS10X10X3/8 GIRT") were
            # forced to "column" below and lost their real profile, then
            # re-appeared as a phantom unlabeled "(beam?)" candidate on the
            # same drawn line.
            if is_girt:
                return "beam"
            # Only perfectly square HSS (e.g. HSS6X6, HSS8X8) are columns;
            # all rectangular HSS spanning between grids are beams.
            return "column" if abs(d1 - d2) < 0.5 else "beam"
        except ValueError:
            return "beam"

    # Abbreviated W-section (depth only — no weight in label, e.g. "W12", "W16")
    w_abbr = re.match(r'(?<![A-Z0-9])W(\d+)$', p)
    if w_abbr:
        # No weight info → treat as beam by default; beam-line override in
        # build_members will further validate against matched vector lines.
        return "beam"

    w = re.match(r'W(\d+)[Xx](\d+)', p)
    if w:
        depth  = int(w.group(1))
        weight = int(w.group(2))

        # Weight-to-depth column thresholds — used by ALL tiers so that a light
        # section (W12X26) near a column symbol is never falsely promoted.
        # A profile only qualifies as a column if its weight meets or exceeds
        # the threshold for its depth.
        _col_thresholds = {
            6:  0,    # W6  — always column
            7:  0,
            8:  0,    # W8  — always column
            9:  0,
            10: 22,   # W10×22+  → column
            12: 40,   # W12×40+  → column  (W12×26/30 stay beam)
            14: 38,   # W14×38+  → column  (W14×22/26/30 stay beam)
            16: 57,   # W16×57+  (W16×26/31/36/40 stay beam)
            18: 71,   # W18×71+  (W18×35/40/46/50 stay beam)
            21: 83,
            24: 94,
            27: 102,
        }
        _is_col_weight = weight >= _col_thresholds.get(depth, 9999)

        # TIERs 1-4 below all ultimately depend on this sheet actually having
        # real column symbols marked on it. On a pure framing/roof plan with
        # zero column symbols anywhere (this project's roof framing sheets
        # only show beams/joists -- columns are only marked once, on the
        # foundation/column plan), the grid-intersection and label-only
        # tiers (2/3/4) used to still fire from weight/depth/position alone,
        # misclassifying short or heavy W-section beam labels as phantom
        # columns -- producing extra/duplicate column members that don't
        # correspond to any real footing. Require at least one real column
        # symbol detected SOMEWHERE on the page before trusting any of that
        # inference; a profile that's unambiguously column-only (PIPE /
        # square HSS, handled in TIER 0 above) is exempt since those are
        # never legitimately beams regardless of the sheet.
        if not column_symbols:
            return "beam"

        # ── TIER 1: near a detected I/H column symbol ─────────────────────────
        # The symbol drawn on the plan is the strongest signal — use it first.
        # BUT only promote to column if the section weight also confirms it.
        # Short beams framing INTO a column have their label placed right next
        # to the column symbol — without the weight check, they get stolen.
        for sym in column_symbols:
            if math.hypot(cx - sym["cx"], cy - sym["cy"]) < SYMBOL_ASSOC_RADIUS:
                if _is_col_weight or depth <= 10:
                    return "column"
                # Light section near symbol = beam framing into column
                break

        # ── TIER 2: at a named grid intersection ──────────────────────────────
        # Columns sit exactly at grid line crossings; beams span between them.
        # Same weight guard: a W12X26 at a grid crossing is a beam, not a column.
        if v_grid and h_grid:
            near_v = any(abs(cx - gx) < GRID_TOL for gx in v_grid)
            near_h = any(abs(cy - gy) < GRID_TOL for gy in h_grid)
            if near_v and near_h and _is_col_weight:
                return "column"

        # ── TIER 3: depth rule — short W-sections are columns on every drawing ─
        # W6 and W8 are almost never used as beams in structural framing plans.
        # W10 sections are columns far more often than beams.
        if depth <= 8:
            return "column"
        if depth == 10 and weight >= 22:
            return "column"

        # ── TIER 4: weight-per-depth heuristic ────────────────────────────────
        # For W12/W14 (used both ways) and larger sections:
        # a high weight-to-depth ratio signals a compact column section.
        if _is_col_weight:
            return "column"

        return "beam"

    return "beam"


# ── Schedule / legend table exclusion ────────────────────────────────────────
def detect_notes_text_zones(page, text_dict=None, min_lines=6, min_avg_words=4.0,
                             cluster_gap=22.0):
    """
    Detect areas of dense multi-line prose -- general notes columns, legend
    paragraphs, disclaimer blocks -- so column-symbol detection can ignore
    anything sitting inside them, on ANY drawing, not just this one.

    Root cause this fixes: a real column callout is an isolated one-to-four
    word label right next to its plan symbol. A general-notes paragraph
    ("10. ALL EXTERIOR WALLS TO BE CONTINUOUSLY SHEATHED...") is many lines
    of ordinary sentences stacked in a column of text, often boxed or
    highlighted, and can itself contain short mark-shaped fragments (a
    section size quoted inside a note, a schedule reference like "COL
    [4-9]") that happen to match the same "letter-prefix + digits" pattern
    detect_column_symbols' mark-proximity check looks for. Nothing
    upstream currently distinguishes "isolated plan callout" from "sentence
    inside a paragraph" -- this does, using a general structural signature
    (line count + words-per-line) rather than any wording specific to one
    sheet, so it generalizes to every future drawing's notes/legend text.

    Root cause of a SECOND, subtler false-negative (found 2026-09-09 on a
    sheet whose general-notes column is drawn ROTATED, reading bottom-to-
    top along the sheet edge -- a very common structural-drawing
    convention): PyMuPDF's own "dict" block segmentation does not treat a
    rotated, word-wrapped paragraph as one block the way it does an
    upright one. It emits ONE TINY BLOCK PER PHYSICAL TEXT LINE (the note
    number "8." is its own block, each wrapped line of the note body is
    its own block, etc.), so no single block from a rotated notes column
    ever reaches `min_lines` on its own -- the whole column silently
    passes the old per-block test and column-symbol detection then runs
    unfiltered inside it, producing a phantom column/beam mark wherever a
    stray vector glyph (a bullet, an underline, a boxed note number)
    happens to sit. This is not specific to one sheet's wording or
    rotation angle; any renderer/layout that fragments a dense paragraph
    into many small blocks defeats the same per-block line count.

    Fix: cluster blocks by simple bounding-box proximity (union-find on
    bbox overlap after expanding each bbox by `cluster_gap`) BEFORE
    applying the line-count/word-density test, so blocks that are really
    one visual paragraph -- whether split by ordinary word-wrap or by a
    rotated renderer's per-line block boundaries -- are evaluated
    together. `cluster_gap` (22pt) comfortably bridges the tight column-
    to-column and label-to-body spacing inside a real notes strip
    (observed 13-26pt on the sheet that exposed this) without bridging to
    an unrelated, normally-spaced plan symbol or dimension string
    elsewhere on the page.

    A cluster qualifies as a notes/prose zone when its merged lines total
    at least `min_lines` AND average at least `min_avg_words` words per
    line -- true of ordinary sentences (whole or fragmented), false of a
    stacked column of short labels (which is what detect_schedule_zones
    already handles separately) and false of an isolated 1-4 word callout.
    """
    _td = text_dict if text_dict is not None else page.get_text("dict")
    raw_blocks = []
    for block in _td.get("blocks", []):
        lines = block.get("lines", [])
        bbox = block.get("bbox")
        if not lines or not bbox:
            continue
        raw_blocks.append((bbox, lines))

    n = len(raw_blocks)
    parent = list(range(n))

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a, b):
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    def _overlaps(a, b):
        return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])

    for i in range(n):
        bi = raw_blocks[i][0]
        ei = (bi[0] - cluster_gap, bi[1] - cluster_gap,
              bi[2] + cluster_gap, bi[3] + cluster_gap)
        for j in range(i + 1, n):
            if _overlaps(ei, raw_blocks[j][0]):
                _union(i, j)

    clusters = {}
    for i in range(n):
        clusters.setdefault(_find(i), []).append(i)

    zones = []
    for idxs in clusters.values():
        cluster_lines = []
        for i in idxs:
            cluster_lines.extend(raw_blocks[i][1])
        if len(cluster_lines) < min_lines:
            continue
        word_counts = []
        for line in cluster_lines:
            words = sum(len(sp.get("text", "").split()) for sp in line.get("spans", []))
            word_counts.append(words)
        if not word_counts:
            continue
        avg_words = sum(word_counts) / len(word_counts)
        if avg_words < min_avg_words:
            continue
        xs0 = [raw_blocks[i][0][0] for i in idxs]
        ys0 = [raw_blocks[i][0][1] for i in idxs]
        xs1 = [raw_blocks[i][0][2] for i in idxs]
        ys1 = [raw_blocks[i][0][3] for i in idxs]
        bx0, by0, bx1, by1 = min(xs0), min(ys0), max(xs1), max(ys1)
        pad = 12.0
        zones.append((bx0 - pad, by0 - pad, bx1 + pad, by1 + pad))
        print(f"[NOTES-ZONE] Dense prose region excluded: "
              f"({bx0:.0f},{by0:.0f})->({bx1:.0f},{by1:.0f}) "
              f"blocks={len(idxs)} lines={len(cluster_lines)} avg_words/line={avg_words:.1f}")
    return zones


def detect_schedule_zones(page, plan_bounds, text_dict=None):
    """
    Detect zones that are purely schedule/legend tables (not part of the
    structural plan) so we don't extract phantom members from them.

    Approach: look for steel-section labels that are OUTSIDE the plan boundary
    entirely (i.e., in the title block, notes column, or border area).
    The plan boundary already correctly clips the extraction region, so we
    only need to exclude labels that are JUST inside the boundary but clearly
    belong to tabular data — identified by extremely tight x-spread (< 8 pt,
    meaning they share almost the exact same x) AND a large y-span (> 250 pt)
    AND a very high label density (≥ 25 labels).

    Previously this used a 12-hit / 30-pt / 150-pt threshold which falsely
    excluded entire column lines on complex framing plans where many beams
    frame into the same grid line, producing a dense vertical label cluster
    that looks superficially like a schedule table.
    """
    bx0, by0, bx1, by1 = plan_bounds

    hits = []
    _td = text_dict if text_dict is not None else page.get_text("dict")
    for block in _td["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span["text"].strip()
                if not text:
                    continue
                cx = (span["bbox"][0] + span["bbox"][2]) / 2
                cy = (span["bbox"][1] + span["bbox"][3]) / 2
                # Scan whole page so schedule tables outside plan_bounds are caught
                for pat in STEEL_PATTERNS:
                    if re.search(pat, text, re.IGNORECASE):
                        hits.append((cx, cy))
                        break

    if len(hits) < 10:
        return []

    # Collect roughly-horizontal drawn lines so we can tell a real schedule TABLE
    # (pure text — almost no structural lines cross it) from a dense BEAM-LABEL
    # column (a grid line that many beams frame into has one beam line crossing
    # near almost every label).  This is the universal discriminator — a count
    # threshold alone can't tell them apart, since a long grid line can carry
    # 30-40 real beam labels.
    h_lines = []   # (x_lo, x_hi, y) of horizontal-ish segments
    try:
        for d in page.get_drawings():
            for it in d.get("items", []):
                if it[0] != "l":
                    continue
                p1, p2 = it[1], it[2]
                if abs(p2.y - p1.y) <= abs(p2.x - p1.x) and abs(p2.x - p1.x) > 20:
                    h_lines.append((min(p1.x, p2.x), max(p1.x, p2.x),
                                    (p1.y + p2.y) / 2))
    except Exception:
        pass

    excluded = []
    # ── Key Plan thumbnail exclusion ──────────────────────────────────────────
    # Exclude Key Plan index map (e.g. area diagrams, garage footprint) in sheet corners
    for block in _td.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span.get("text", "").strip().upper()
                if "KEY PLAN" in t or "KEYPLAN" in t:
                    bx0, by0, bx1, by1 = span["bbox"]
                    # Key Plan box typically extends 250 pt up/around the "KEY PLAN" label
                    kp_zone = (
                        max(0, bx0 - 220),
                        max(0, by0 - 320),
                        bx1 + 220,
                        by1 + 80
                    )
                    excluded.append(kp_zone)
                    print(f"[EXCLUDE] Key Plan exclusion zone detected: ({kp_zone[0]:.0f}, {kp_zone[1]:.0f}) -> ({kp_zone[2]:.0f}, {kp_zone[3]:.0f})")
    used = [False] * len(hits)

    for i, (ax, ay) in enumerate(hits):
        if used[i]:
            continue
        cluster = [(ax, ay)]
        used[i] = True
        for j, (bx, by) in enumerate(hits):
            if not used[j] and abs(ax - bx) < 8:   # very tight: < 8pt x-spread
                cluster.append((bx, by))
                used[j] = True

        # Require 25+ labels in that tiny x-band — only a true printed schedule
        # has this many entries at virtually the same x position.
        # Structural framing plans never concentrate this many beam labels on a
        # single column line with < 8pt x variation.
        if len(cluster) < 25:
            continue

        xs = [p[0] for p in cluster]
        ys = [p[1] for p in cluster]
        x_spread = max(xs) - min(xs)
        y_spread = max(ys) - min(ys)

        if x_spread < 8 and y_spread > 250:
            # Structural test: count beam lines that cross this label column.
            # A schedule table has almost none; a framing grid line has roughly
            # one per beam label.  If many cross, these are BEAM LABELS — keep them.
            cx_band = (min(xs) + max(xs)) / 2.0
            y0, y1 = min(ys), max(ys)
            crossing = sum(1 for lx0, lx1, ly in h_lines
                           if y0 - 30 <= ly <= y1 + 30
                           and lx0 - 40 <= cx_band <= lx1 + 40)
            if crossing >= 0.4 * len(cluster):
                print(f"[SCHEDULE] kept x={cx_band:.0f} n={len(cluster)} — "
                      f"{crossing} beam lines cross (framing, NOT a table)")
                continue
            zone = (min(xs) - 60, min(ys) - 40, max(xs) + 60, max(ys) + 40)
            excluded.append(zone)
            print(f"[SCHEDULE] Col-cluster x=[{min(xs):.0f},{max(xs):.0f}] "
                  f"y=[{min(ys):.0f},{max(ys):.0f}] n={len(cluster)}")



    return excluded


# ── Profile extraction (within plan boundary only) ────────────────────────────
def extract_profiles(page, page_w, page_h, plan_bounds, text_dict=None):
    """
    Extract steel section labels from within the plan boundary.

    CAD PDFs frequently split a label like 'W18X40' across two text spans
    ('W18' and 'X40').  We match at both span-level AND full-line-level to
    catch every case, then deduplicate by proximity.
    """
    bx0, by0, bx1, by1 = plan_bounds
    excluded_zones = detect_schedule_zones(page, plan_bounds, text_dict=text_dict)
    profiles, seen = [], []

    def _try_add(text, cx, cy, rot_pass=0, bbox_w=20.0, bbox_h=8.0, angle=0.0):
        if not text:
            return
        # Scan the ENTIRE page for beam labels — do NOT filter by plan_bounds here.
        # Previously _LABEL_EDGE=120pt caused the entire right (or top/bottom) half
        # of a drawing to be silently dropped whenever plan_bounds was slightly
        # mis-detected.  STEEL_PATTERNS regex is specific enough that title-block
        # text never matches; schedule tables are excluded by detect_schedule_zones.
        # The label→line matcher (LABEL_R=130pt) and the structural length filter
        # act as the real proximity guard — no boundary pre-filter needed.
        _LABEL_EDGE = max(page_w, page_h)   # whole-page scan
        if not (bx0 - _LABEL_EDGE <= cx <= bx1 + _LABEL_EDGE and
                by0 - _LABEL_EDGE <= cy <= by1 + _LABEL_EDGE):
            return
        if any(zx0 <= cx <= zx1 and zy0 <= cy <= zy1
               for zx0, zy0, zx1, zy1 in excluded_zones):
            return
        for pat in STEEL_PATTERNS:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                # Dedup radius 10 pt (was 20): dense framing plans have labels
                # as close as 10-15 pt; 20 pt dropped every second label.
                if not any(math.hypot(cx - sx, cy - sy) < 10
                           for sx, sy in seen):
                    seen.append((cx, cy))
                    # Three signals to determine vertical orientation:
                    # 1. rot_pass in (1,2): OCR found rotated text
                    # 2. |angle| > 70°: span["dir"] is near-vertical (≈90°).
                    #    IMPORTANT: use 70°, NOT 45°.  Diagonal beams in
                    #    rotated-grid drawings have labels at 30–60°; a 45°
                    #    threshold misclassifies them as vertical, swaps their
                    #    bbox, and then breaks the direction guard in
                    #    detect_beam_lines.  Only genuine 90°-rotated Revit
                    #    labels should trip this signal.
                    # 3. bbox_h > bbox_w*1.5: tall bbox = Revit pre-rotation
                    _is_vert = (rot_pass in (1, 2)
                                or abs(angle) > 70.0
                                or bbox_h > bbox_w * 1.5)
                    # Swap bbox dims for Revit pre-rotation: rotated text is
                    # stored with pre-rotation dimensions (wide instead of tall).
                    if _is_vert and bbox_w > bbox_h:
                        eff_w, eff_h = bbox_h, bbox_w
                    else:
                        eff_w, eff_h = bbox_w, bbox_h
                    profiles.append({
                        "profile": normalize_profile(m.group(0)),
                        "cx": cx, "cy": cy,
                        "dir_hint": "V" if _is_vert else "H",
                        "text_angle": angle,
                        # bbox dimensions — used by detect_beam_lines to infer
                        # expected beam direction (wide text → H beam; tall → V)
                        "bbox_w": max(eff_w, 1.0),
                        "bbox_h": max(eff_h, 1.0),
                        # "GIRT" appearing in the same text as the profile match
                        # (e.g. "HSS10X10X3/8 GIRT") means this is a horizontal
                        # secondary framing member, never a column — see
                        # classify_member's is_girt override.
                        "is_girt": "GIRT" in text.upper(),
                    })
                break

    _td = text_dict if text_dict is not None else page.get_text("dict")
    for block in _td["blocks"]:
        for line in block.get("lines", []):
            spans = line.get("spans", [])

            # ── Span-level: precise position per span ─────────────────────
            for span in spans:
                bbox = span["bbox"]
                cx = (bbox[0] + bbox[2]) / 2
                cy = (bbox[1] + bbox[3]) / 2
                _dx, _dy = span.get("dir", (1.0, 0.0))
                _ang = math.degrees(math.atan2(-_dy, _dx))
                _try_add(span["text"].strip(), cx, cy,
                         rot_pass=span.get("rot_pass", 0),
                         bbox_w=bbox[2] - bbox[0],
                         bbox_h=bbox[3] - bbox[1],
                         angle=_ang)

            # ── Line-level: join all spans → catches "W18" + "X40" splits ─
            line_text = "".join(s["text"] for s in spans).strip()
            if line.get("bbox") and line_text:
                lb = line["bbox"]
                lx = (lb[0] + lb[2]) / 2
                ly = (lb[1] + lb[3]) / 2
                first_pass = spans[0].get("rot_pass", 0) if spans else 0
                if spans:
                    _ldx, _ldy = spans[0].get("dir", (1.0, 0.0))
                    _lang = math.degrees(math.atan2(-_ldy, _ldx))
                else:
                    _lang = 0.0
                _try_add(line_text, lx, ly, rot_pass=first_pass,
                         bbox_w=lb[2] - lb[0], bbox_h=lb[3] - lb[1],
                         angle=_lang)

    print(f"[EXTRACT] {len(profiles)} profiles found in plan")
    return profiles


def precompute_span_grids(profiles: list, plan_bounds: tuple,
                          page_w: float, page_h: float) -> tuple:
    """
    Quick pre-pass: classify profiles without grid context to find columns,
    then build span grids from their positions.

    Used by the /analyse endpoint to generate reliable span grids BEFORE
    detect_beam_lines_raster and build_members are called, so both can use
    the same accurate column-position-based grids.

    Returns (span_v_grid, span_h_grid) as sorted lists of pixel positions.
    """
    _pb = plan_bounds or (0, 0, page_w, page_h)

    col_xs: list[float] = []
    col_ys: list[float] = []
    for p in profiles:
        mt = classify_member(p["profile"], p["cx"], p["cy"],
                             column_symbols=None, v_grid=None, h_grid=None,
                             is_girt=p.get("is_girt", False))
        if mt == "column":
            col_xs.append(p["cx"])
            col_ys.append(p["cy"])

    def _dedup(vals: list, tol: float = 20.0) -> list:
        out: list = []
        for v in sorted(vals):
            if not out or abs(v - out[-1]) > tol:
                out.append(v)
        return out

    svg = _dedup(col_xs) if col_xs else []
    shg = _dedup(col_ys) if col_ys else []

    # Always include plan-boundary edges so edge beams get a span line
    svg = _dedup(sorted(svg + [_pb[0], _pb[2]]))
    shg = _dedup(sorted(shg + [_pb[1], _pb[3]]))

    print(f"[SPAN_GRIDS] V({len(svg)}): {[round(x) for x in svg]}")
    print(f"[SPAN_GRIDS] H({len(shg)}): {[round(y) for y in shg]}")
    return svg, shg


def _snap_endpoint_to_column(x: float, y: float,
                              column_symbols: list,
                              snap_radius: float = 90.0) -> tuple[float, float]:
    """Return the position of the nearest column symbol within snap_radius."""
    if not column_symbols:
        return x, y
    best = min(column_symbols, key=lambda s: math.hypot(s["cx"] - x, s["cy"] - y))
    if math.hypot(best["cx"] - x, best["cy"] - y) <= snap_radius:
        return best["cx"], best["cy"]
    return x, y


def _column_pair_span(cx: float, cy: float, beam_dir: str,
                      column_symbols: list, pts_per_foot: float,
                      max_span_pt: float = 380.0) -> dict | None:
    """
    Find the two nearest column symbols that a beam label sits BETWEEN and
    return span endpoints (exact column-to-column positions).

    max_span_pt caps the result so multi-bay false matches are rejected.
    At 1/8"=1'-0" scale, 380 pt ≈ 42 ft — typical max single bay.
    """
    if not column_symbols:
        return None

    if beam_dir in ("H", "D"):
        for tol in (25, 50, 80):
            row    = [s for s in column_symbols if abs(s["cy"] - cy) <= tol]
            lefts  = [s for s in row if s["cx"] < cx - 5]
            rights = [s for s in row if s["cx"] > cx + 5]
            if lefts and rights:
                c1 = max(lefts,  key=lambda s: s["cx"])
                c2 = min(rights, key=lambda s: s["cx"])
                break
        else:
            return None
    else:  # V
        for tol in (25, 50, 80):
            col     = [s for s in column_symbols if abs(s["cx"] - cx) <= tol]
            tops    = [s for s in col if s["cy"] < cy - 5]
            bottoms = [s for s in col if s["cy"] > cy + 5]
            if tops and bottoms:
                c1 = max(tops,    key=lambda s: s["cy"])
                c2 = min(bottoms, key=lambda s: s["cy"])
                break
        else:
            return None

    length_pt = math.hypot(c2["cx"] - c1["cx"], c2["cy"] - c1["cy"])
    if length_pt > max_span_pt:
        return None  # multi-bay false match — let grid fallback handle it
    return {
        "x1": c1["cx"], "y1": c1["cy"],
        "x2": c2["cx"], "y2": c2["cy"],
        "length_ft": round(length_pt / pts_per_foot, 1) if pts_per_foot > 0 else 0.0,
    }


# ── Build members + summary ───────────────────────────────────────────────────
def _span_valid(bx1f, by1f, bx2f, by2f, lx_frac, ly_frac, beam_dir) -> bool:
    """
    Sanity-check: the label must lie on (or very near) the computed span line.

    Why this matters
    ----------------
    For vector PDFs detect_beam_lines() guarantees this by construction.
    For the grid-based fallback (compute_beam_span), wrong grid-line matches
    can produce span endpoints that are on the opposite side of the plan from
    the label — the line appears visually far from the chip on screen.

    Rules (all tolerances as fractions of the page dimension):
      H-beam  — span Y must be within PERP_TOL of label Y
                 label X must fall inside [bx1−EXT_TOL, bx2+EXT_TOL]
      V-beam  — span X must be within PERP_TOL of label X
                 label Y must fall inside [by1−EXT_TOL, by2+EXT_TOL]
    """
    # PERP_TOL: how far (as fraction of page) the label can sit from the span's
    # perpendicular axis.  A correct span always places the label ≤ ~5 ft from
    # the centreline (label is ON the beam).  The old 15% tolerance was too
    # loose: on a 1728 pt page at 3/16" scale, 15% = 259 pt ≈ 19 ft — wide
    # enough to pass a wrong-row grid fallback span (beam on row K but grid
    # snapped to row H→M, putting the midpoint 2-3 rows off).
    # 8% = ~138 pt ≈ 10 ft at 3/16" — still generous for offset labels but
    # tight enough to reject spans that land on the wrong grid row.
    PERP_TOL = 0.08
    EXT_TOL  = 0.20   # allow label up to 20 % beyond an endpoint (skewed labels)

    if beam_dir == "H":
        span_y = (by1f + by2f) / 2
        if abs(ly_frac - span_y) > PERP_TOL:
            return False
        x_lo = min(bx1f, bx2f) - EXT_TOL
        x_hi = max(bx1f, bx2f) + EXT_TOL
        return x_lo <= lx_frac <= x_hi
    elif beam_dir == "V":
        span_x = (bx1f + bx2f) / 2
        if abs(lx_frac - span_x) > PERP_TOL:
            return False
        y_lo = min(by1f, by2f) - EXT_TOL
        y_hi = max(by1f, by2f) + EXT_TOL
        return y_lo <= ly_frac <= y_hi
    else:  # "D"
        # For diagonal beams, we matched the vector line directly, so it is inherently valid.
        return True


def build_members(profiles, page_w, page_h,
                  column_symbols=None, v_grid=None, h_grid=None,
                  pts_per_foot: float = 0.0,
                  beam_dirs: dict = None,
                  beam_line_map: dict = None,
                  plan_bounds: tuple = None,
                  is_vector: bool = False):
    """
    Two-pass pipeline that prevents beam labels near a column symbol from
    being falsely promoted to "column" (the old fan-out problem).

    Pass 1 — One-to-one symbol→profile matching (greedy, closest-first).
              Each column symbol claims the single nearest unclaimed profile
              within SYMBOL_ASSOC_RADIUS.  Those profiles are definitively
              columns; no other profile can be claimed by the same symbol.

    Pass 2 — All remaining profiles are classified by TIER 2 / 3 / 4 only
              (no TIER 1 — that was handled exclusively in Pass 1).

    Position snapping is applied afterwards:
      Snap 1 — snap to nearest grid intersection.
      Snap 2 — snap to nearest unclaimed symbol (fallback).
    """
    members = []

    # ── Pass 1: exclusive symbol → profile matching ───────────────────────────
    symbol_matched_cols: set[int] = set()   # profile indices confirmed as columns
    profile_sym_pos: dict[int, tuple] = {}  # p_idx → (sx_frac, sy_frac) of matched symbol
    # Stage 3 (2026-07-17 rebuild): keep the matched symbol's own index too,
    # not just its position, so Pass 2 can look up the Symbol Classification
    # Engine's category for it (column_symbols[s_idx]["category"], set by
    # classify_and_filter_symbols before build_members is ever called) --
    # this is the primary, mark-matched column pathway (the one that
    # actually produces most foundation-plan columns; emit_symbol_columns is
    # the secondary, no-label-symbol fallback), so this is the path that
    # needs the footing/column split to have any real-world effect.
    profile_sym_idx: dict[int, int] = {}
    if column_symbols:
        # Build all (distance, symbol_idx, profile_idx) pairs within radius
        candidates = []
        for s_idx, sym in enumerate(column_symbols):
            for p_idx, p in enumerate(profiles):
                # A GIRT label is never a column, no matter how close it sits
                # to a column symbol (e.g. a roof-edge girt framing right into
                # a corner column) -- skip it so it falls through to Pass 2's
                # classify_member, which now returns "beam" for is_girt.
                if p.get("is_girt"):
                    continue
                d = math.hypot(p["cx"] - sym["cx"], p["cy"] - sym["cy"])
                if d < SYMBOL_ASSOC_RADIUS:
                    candidates.append((d, s_idx, p_idx))
        candidates.sort()          # process closest pairs first
        used_s: set[int] = set()
        used_p: set[int] = set()
        for d, s_idx, p_idx in candidates:
            if s_idx not in used_s and p_idx not in used_p:
                symbol_matched_cols.add(p_idx)
                used_s.add(s_idx)
                used_p.add(p_idx)
                # Store the symbol position so the frontend region filter can
                # check it — the user draws around the SYMBOL, not the label
                profile_sym_pos[p_idx] = (
                    round(column_symbols[s_idx]["cx"] / page_w, 4),
                    round(column_symbols[s_idx]["cy"] / page_h, 4),
                )
                profile_sym_idx[p_idx] = s_idx
        print(f"[BUILD] {len(symbol_matched_cols)} profiles matched to column symbols "
              f"(of {len(column_symbols)} symbols, {len(profiles)} profiles)")

    # ── Span grids: build reliable v/h grids for beam span computation ────────
    # Text-label grid detection is noisy for raster images (dense false
    # positives near the plan perimeter → tiny spans).  Column X positions are
    # far more reliable: every column sits at a real grid intersection.
    #
    # Strategy:
    #  1. Quick-classify all profiles to find columns (no symbol/grid context).
    #  2. If the text-derived v_grid is too dense (min spacing < 40 units, which
    #     is ~4 ft at 1/8" scale — physically impossible for structural steel),
    #     replace it with the sorted column X positions.
    #  3. Same for h_grid using column Y positions.
    #  4. If still empty after column fallback, use plan-boundary or page extremes
    #     so every beam at least gets a full-width/full-height line.

    pre_col_xs: list[float] = []
    pre_col_ys: list[float] = []
    for p_idx, p in enumerate(profiles):
        if p_idx in symbol_matched_cols:
            pre_col_xs.append(p["cx"])
            pre_col_ys.append(p["cy"])
        else:
            mt = classify_member(p["profile"], p["cx"], p["cy"],
                                 column_symbols=None, v_grid=None, h_grid=None,
                                 is_girt=p.get("is_girt", False))
            if mt == "column":
                pre_col_xs.append(p["cx"])
                pre_col_ys.append(p["cy"])

    def _dedup(vals: list[float], tol: float = 18) -> list[float]:
        out: list[float] = []
        for v in sorted(vals):
            if not out or abs(v - out[-1]) > tol:
                out.append(v)
        return out

    def _grid_too_dense(grid: list, span: float, min_gap: float = 40.0) -> bool:
        """True when the grid has very closely-spaced entries (false positives)."""
        if len(grid) < 2:
            return False
        gaps = [b - a for a, b in zip(sorted(grid), sorted(grid)[1:])]
        return min(gaps) < min_gap

    # Build effective span grids
    _pb = plan_bounds or (0, 0, page_w, page_h)
    span_v_grid = v_grid or []
    span_h_grid = h_grid or []

    if _grid_too_dense(span_v_grid, page_w) or not span_v_grid:
        span_v_grid = _dedup(pre_col_xs, tol=20) if pre_col_xs else []
    if _grid_too_dense(span_h_grid, page_h) or not span_h_grid:
        span_h_grid = _dedup(pre_col_ys, tol=20) if pre_col_ys else []

    # Always include plan-boundary edges so beams beyond the last column
    # still get a line (left/right or top/bottom of the plan becomes one endpoint).
    if not span_v_grid:
        span_v_grid = [_pb[0], _pb[2]]
    else:
        span_v_grid = _dedup(sorted(span_v_grid + [_pb[0], _pb[2]]), tol=20)
    if not span_h_grid:
        span_h_grid = [_pb[1], _pb[3]]
    else:
        span_h_grid = _dedup(sorted(span_h_grid + [_pb[1], _pb[3]]), tol=20)

    print(f"[BUILD] span_v_grid({len(span_v_grid)}): {[round(x) for x in span_v_grid]}")
    print(f"[BUILD] span_h_grid({len(span_h_grid)}): {[round(y) for y in span_h_grid]}")

    # ── Pass 2: classify + snap ───────────────────────────────────────────────
    claimed_symbols: set[int] = set()

    for p_idx, p in enumerate(profiles):
        # Determine member type
        if p_idx in symbol_matched_cols:
            mtype = "column"
        else:
            # TIER 1 is handled exclusively in Pass 1 — pass column_symbols=None
            # here so classify_member uses TIER 2 / 3 / 4 only.
            mtype = classify_member(
                p["profile"], p["cx"], p["cy"],
                column_symbols=None,
                v_grid=v_grid, h_grid=h_grid,
                is_girt=p.get("is_girt", False),
            )

        # ── Beam-line override ────────────────────────────────────────────────
        # detect_beam_lines() matches labels that sit ON a drawn structural
        # centreline at (or near) its midpoint.  Column labels are placed AT
        # the column symbol — never at the mid-span of a long beam centreline.
        # If a profile (even one claimed by a column symbol in Pass 1) has a
        # long vector-line match, it IS a beam.  This corrects false-positive
        # column symbols (annotation boxes, beam flanges, etc.) that grab
        # nearby beam labels in Pass 1.
        _MIN_BEAM_PT = 60   # ≈ 6 ft at 1/8" — anything shorter is a tick/stub
        # Definitive column sections — PIPE is ALWAYS a column (a column
        # viewed in plan often sits on a grid/wall line, so the line match
        # must NOT demote it to a beam).
        _pu = (p.get("profile") or "").upper()
        _definitive_col = bool(re.match(r'PIPE', _pu))
        _hssm = re.match(r'HSS([\d.]+)[Xx]([\d.]+)', _pu)
        _is_square_hss = False
        if _hssm:
            try:
                if abs(float(_hssm.group(1)) - float(_hssm.group(2))) < 0.5:
                    _is_square_hss = True
                    # Square HSS is only "definitively" a column when a real
                    # column SYMBOL (I/H mark / baseplate) was actually
                    # matched to it in Pass 1 above -- that's graphical
                    # confirmation, not a shape guess. Square HSS is routinely
                    # used as a BEAM too (framing between two supports, with
                    # or without a "GIRT" callout), so without that symbol
                    # evidence a confirmed vector-line match below must be
                    # allowed to override it, same as every other profile
                    # type. This still keeps HSS6X6 columns on foundation /
                    # rotated sheets classified correctly (those DO have a
                    # matched symbol), it just stops forcing every square HSS
                    # with no symbol at all to "column" regardless of a real
                    # beam-length line match.
                    if p_idx in symbol_matched_cols:
                        _definitive_col = True      # square HSS w/ real symbol → column
            except ValueError:
                pass
        if mtype == "column" and beam_line_map and not _definitive_col:
            _hit = beam_line_map.get(p_idx)
            if _hit and _hit.get("length_pt", 0) >= _MIN_BEAM_PT:
                mtype = "beam"
                if p_idx in symbol_matched_cols:
                    symbol_matched_cols.discard(p_idx)

        # ── Square-HSS symbol override ────────────────────────────────────────
        # A square HSS label can get claimed by Pass 1 purely because it sits
        # close to a real column symbol -- beams routinely frame INTO a
        # column, so their label often lands right next to one. That
        # proximity alone doesn't make the label itself a column. If it also
        # has its own confirmed, beam-length vector-line match, trust that
        # structural evidence over the symbol proximity, exactly like the
        # override above already does for every other profile type.
        if mtype == "column" and _is_square_hss and p_idx in symbol_matched_cols and beam_line_map:
            _hit = beam_line_map.get(p_idx)
            if _hit and _hit.get("length_pt", 0) >= _MIN_BEAM_PT:
                mtype = "beam"
                symbol_matched_cols.discard(p_idx)

        # ── Section-type override ─────────────────────────────────────────────
        # Light W-sections (W10 weight<22, W12 weight<26) are NEVER used as
        # columns in structural steel framing.  If a false column symbol claimed
        # one of these labels in Pass 1 and the beam-line override didn't fire
        # (e.g. no matching vector line found), trust the section properties and
        # reclassify back to beam.
        if mtype == "column" and p_idx in symbol_matched_cols:
            _wm = re.match(r'W(\d+)[Xx](\d+)', (p.get("profile") or "").upper())
            if _wm:
                _sd, _sw = int(_wm.group(1)), int(_wm.group(2))
                _clearly_beam = (
                    (_sd == 10 and _sw < 22) or
                    (_sd == 12 and _sw < 26) or
                    (_sd >= 14 and _sw < 30)
                )
                if _clearly_beam:
                    mtype = "beam"
                    symbol_matched_cols.discard(p_idx)

        # Angle sections (L-shapes) and small HSS (nominal ≤ 3.5 in) are
        # lacing / bracing / anchor ties -- never a primary building column
        # in standard steel construction (real columns here run HSS6X6 and
        # up, or W-shapes). These labels routinely sit right next to a real
        # column (a brace frames directly into the column it's anchored to,
        # or the text is even just part of a general note like "HSS3X3 & L3X3
        # BRACING AT EA ROOF DAVIT ANCHOR" with no drawn member at all there),
        # so classify_member's own shape-based default or a Pass-1 symbol-
        # proximity match can tag them "column" with no real evidence. Applies
        # regardless of symbol_matched_cols -- unlike the checks above, this
        # one isn't conditioned on HOW it became "column", because an angle or
        # a 3x3 HSS is never a column no matter which path produced that
        # classification.
        if mtype == "column":
            _pu2 = (p.get("profile") or "").upper()
            _is_angle = bool(re.match(r'^L\d', _pu2))
            _hsm2 = re.match(r'^HSS([\d.]+)[Xx]([\d.]+)', _pu2)
            _is_small_hss = False
            if _hsm2:
                try:
                    _is_small_hss = max(float(_hsm2.group(1)), float(_hsm2.group(2))) <= 3.5
                except ValueError:
                    pass
            if _is_angle or _is_small_hss:
                mtype = "beam"
                symbol_matched_cols.discard(p_idx)

        render_cx, render_cy = p["cx"], p["cy"]
        snapped = False

        if mtype == "column":
            # Snap 1: snap to nearest grid intersection
            if v_grid and h_grid:
                nearest_vx = min(v_grid, key=lambda gx: abs(p["cx"] - gx))
                nearest_hy = min(h_grid, key=lambda gy: abs(p["cy"] - gy))
                if (abs(p["cx"] - nearest_vx) < GRID_SNAP_RADIUS and
                        abs(p["cy"] - nearest_hy) < GRID_SNAP_RADIUS):
                    render_cx = nearest_vx
                    render_cy = nearest_hy
                    snapped = True

            # Snap 2: snap to nearest unclaimed column symbol (fallback)
            if not snapped and column_symbols:
                best, best_dist, best_idx = None, float("inf"), -1
                for idx, sym in enumerate(column_symbols):
                    if idx in claimed_symbols:
                        continue
                    d = math.hypot(p["cx"] - sym["cx"], p["cy"] - sym["cy"])
                    if d < best_dist:
                        best_dist, best, best_idx = d, sym, idx
                if best and best_dist < SYMBOL_SNAP_RADIUS:
                    render_cx = best["cx"]
                    render_cy = best["cy"]
                    claimed_symbols.add(best_idx)
                    snapped = True  # noqa: F841

        # ── Beam / Joist direction, length, and span endpoints ────────────────
        beam_dir = None
        length_ft = 0.0
        bx1 = by1 = bx2 = by2 = None

        if mtype in ("beam", "joist"):
            line_hit = (beam_line_map or {}).get(p_idx)

            lx_frac = p["cx"] / page_w
            ly_frac = p["cy"] / page_h

            # Determine whether the vector line match is trustworthy.
            # Two rejection criteria:
            #   (A) segment too short  → dimension tick / hatch stub
            #   (B) label is far from the segment AND _span_valid fails →
            #       annotation / leader line was picked over the real beam
            #       (happens in complex plans with many non-beam lines).
            # A rejected match falls through to the grid-based fallback.
            _use_line_hit = False
            if line_hit:
                MIN_STRUCT_PT = 8    # ≈ 0.9 ft at 1/8" scale — allow short real beams
                beam_dir  = line_hit["dir"]
                length_pt = line_hit["length_pt"]

                # A W-section matching a DIAGONAL line is usually a false match to a
                # stair / brace / section-cut line (those run at ~45°).  BUT on a
                # SKEWED / fanned framing plan the whole grid is rotated a few
                # degrees, so a real beam's matched line is "D" at only a SLIGHT
                # off-axis angle.  Reject only STEEP diagonals; keep gently-angled
                # ones so the overlay follows the actual skewed beam instead of
                # being flattened to horizontal/vertical by the grid fallback.
                _is_w_section = bool(re.match(r'W\d+[Xx]\d+', (p.get("profile") or "").upper()))
                if _is_w_section and beam_dir == "D":
                    _adx = line_hit["x2"] - line_hit["x1"]
                    _ady = line_hit["y2"] - line_hit["y1"]
                    _ang = abs(math.degrees(math.atan2(_ady, _adx))) % 180
                    _off = min(_ang, abs(_ang - 90), abs(_ang - 180))  # ° off nearest axis
                    if _off > 35:
                        print(f"[BUILD] Rejected steep-diagonal match for W-section "
                              f"{p['profile']} ({_off:.0f}° off-axis) — stair/brace line")
                        line_hit = None
                    # else: a gently-angled match on a skewed plan → keep it, so the
                    # overlay preserves the real beam angle.

                if line_hit and length_pt < MIN_STRUCT_PT:
                    print(f"[BUILD] Vector match too short ({length_pt:.0f} pt) "
                          f"for {p['profile']} — dropped as annotation line")
                elif line_hit:
                    # ── Perpendicular-distance validation ─────────────────────
                    # Compute how far the label sits from the matched segment.
                    # Labels placed on the beam centreline are ≤ 20 pt away.
                    # Leader-line labels can be up to ~80 pt away.
                    # If the distance exceeds 80 pt, apply _span_valid as a
                    # geometric sanity check; only reject if that also fails.
                    _vx1, _vy1 = line_hit["x1"], line_hit["y1"]
                    _vx2, _vy2 = line_hit["x2"], line_hit["y2"]
                    _vdx = _vx2 - _vx1
                    _vdy = _vy2 - _vy1
                    _vln = math.hypot(_vdx, _vdy)
                    _perp_ok = True
                    if _vln > 0:
                        _tp = (((p["cx"] - _vx1) * _vdx + (p["cy"] - _vy1) * _vdy)
                               / (_vln * _vln))
                        _tc = max(0.0, min(1.0, _tp))
                        _perp_dist = math.hypot(
                            p["cx"] - (_vx1 + _tc * _vdx),
                            p["cy"] - (_vy1 + _tc * _vdy))
                        # Perpendicular distance limit (150 pt ≈ 16 ft) to allow callouts positioned above/below
                        # mechanical units and section cuts without dropping their real drawn beam line.
                        if _perp_dist > 150.0:
                            _perp_ok = False
                            print(f"[BUILD] Rejected distant vector match for "
                                  f"{p['profile']} (perp={_perp_dist:.1f} pt > 150pt) — distant note callout")

                    if _perp_ok:
                        _use_line_hit = True
                        length_ft = (round(length_pt / pts_per_foot, 1)
                                     if pts_per_foot > 0 else 0.0)
                        bx1 = round(line_hit["x1"] / page_w, 4)
                        by1 = round(line_hit["y1"] / page_h, 4)
                        bx2 = round(line_hit["x2"] / page_w, 4)
                        by2 = round(line_hit["y2"] / page_h, 4)
                        # Chip renders at the TRUE midpoint of the span so the
                        # chip and the SVG line always coincide visually.
                        render_cx = (line_hit["x1"] + line_hit["x2"]) / 2
                        render_cy = (line_hit["y1"] + line_hit["y2"]) / 2

            if not _use_line_hit:
                # ── FALLBACK: grid-based approximation ──────────────────────
                # Runs for both vector and raster PDFs.
                # Always try BOTH H and V spans and pick the LONGER one.
                # The correct structural direction always spans the full bay
                # (longer dimension), so the wrong direction is always shorter.
                # This eliminates wrong-direction lines caused by unreliable
                # detect_beam_directions() results near openings / dense areas.
                def _try_span(direction):
                    if not (v_grid and h_grid):
                        return None
                    # Use ONLY real detected column grid positions — no plan-boundary
                    # extension.  Adding plan boundaries as synthetic columns caused
                    # two bugs: (a) very wide spans that were cleared by the 65%-plan
                    # sanity check, leaving real beams with no line; (b) stray labels
                    # near the plan edge getting full-width flying lines.
                    return compute_beam_span(
                        p["cx"], p["cy"], v_grid, h_grid, pts_per_foot, direction)

                _span_h = _try_span("H")
                _span_v = _try_span("V")
                _len_h  = _span_h["length_ft"] if _span_h else 0.0
                _len_v  = _span_v["length_ft"] if _span_v else 0.0

                # Detected direction is highly reliable; fall back to longer span if direction is missing
                _hint = ((beam_dirs or {}).get(p_idx) or p.get("dir_hint", "H"))
                if _hint == "V" and _span_v:
                    span, beam_dir = _span_v, "V"
                elif _hint == "H" and _span_h:
                    span, beam_dir = _span_h, "H"
                elif _len_h > _len_v:
                    span, beam_dir = _span_h, "H"
                elif _len_v > _len_h:
                    span, beam_dir = _span_v, "V"
                elif _hint == "V":
                    span, beam_dir = _span_v, "V"
                else:
                    span, beam_dir = _span_h, "H"

                # If primary direction failed validation, try the other.
                if span:
                    _bx1 = round(span["x1"] / page_w, 4)
                    _by1 = round(span["y1"] / page_h, 4)
                    _bx2 = round(span["x2"] / page_w, 4)
                    _by2 = round(span["y2"] / page_h, 4)
                    if not _span_valid(_bx1, _by1, _bx2, _by2, lx_frac, ly_frac, beam_dir):
                        print(f"[BUILD] Grid span invalid for {p['profile']} "
                              f"dir={beam_dir} — trying opposite direction")
                        alt_dir = "V" if beam_dir == "H" else "H"
                        alt_span = _try_span(alt_dir)
                        if alt_span:
                            ab1 = round(alt_span["x1"] / page_w, 4)
                            ab2 = round(alt_span["y1"] / page_h, 4)
                            ab3 = round(alt_span["x2"] / page_w, 4)
                            ab4 = round(alt_span["y2"] / page_h, 4)
                            if _span_valid(ab1, ab2, ab3, ab4, lx_frac, ly_frac, alt_dir):
                                span = alt_span
                                _bx1, _by1, _bx2, _by2 = ab1, ab2, ab3, ab4
                                beam_dir = alt_dir
                            else:
                                span = None   # both directions invalid
                        else:
                            span = None

                if span:
                    _bx1 = round(span["x1"] / page_w, 4)
                    _by1 = round(span["y1"] / page_h, 4)
                    _bx2 = round(span["x2"] / page_w, 4)
                    _by2 = round(span["y2"] / page_h, 4)
                    if _span_valid(_bx1, _by1, _bx2, _by2, lx_frac, ly_frac, beam_dir):
                        length_ft = span["length_ft"]
                        bx1, by1, bx2, by2 = _bx1, _by1, _bx2, _by2
                        render_cx = (span["x1"] + span["x2"]) / 2
                        render_cy = (span["y1"] + span["y2"]) / 2
                    else:
                        print(f"[BUILD] Grid span discarded for {p['profile']} "
                              f"(label=({lx_frac:.3f},{ly_frac:.3f}) "
                              f"span=({_bx1:.3f},{_by1:.3f})->({_bx2:.3f},{_by2:.3f})"
                              f" dir={beam_dir})")

        # ── Final span sanity check ──────────────────────────────────────────
        # Reject spans that exceed 65% of the plan in their primary direction.
        # Direction-aware to handle diagonal beams in rotated grids:
        #   H beam → only check width   (diagonal X-projection can be large)
        #   V beam → only check height
        #   D beam → check total length vs plan diagonal
        # This kills full-width boundary/grid lines (100%) while keeping
        # legitimate 3-of-5-bay beams (~60% plan).
        if plan_bounds and bx1 is not None and mtype == "beam":
            _pb_h_pt = plan_bounds[3] - plan_bounds[1]
            _pb_w_pt = plan_bounds[2] - plan_bounds[0]
            _span_h = abs(by2 - by1) * page_h if (by1 is not None and by2 is not None) else 0
            _span_w = abs(bx2 - bx1) * page_w if (bx1 is not None and bx2 is not None) else 0
            _too_long = False
            # Only reject spans that exceed 90% of the plan — this keeps grid/boundary
            # lines out while allowing genuine multi-bay beams (~80% of plan).
            if beam_dir == "H":
                _too_long = _span_w > _pb_w_pt * 0.90
            elif beam_dir == "V":
                _too_long = _span_h > _pb_h_pt * 0.90
            elif beam_dir == "D":
                _too_long = math.hypot(_span_w, _span_h) > math.hypot(_pb_w_pt, _pb_h_pt) * 0.90
            else:
                _too_long = (_span_h > _pb_h_pt * 0.90 or _span_w > _pb_w_pt * 0.90)
            if _too_long:
                print(f"[BUILD] Span too long for {p['profile']} dir={beam_dir} "
                      f"w={_span_w:.0f} h={_span_h:.0f} vs plan "
                      f"w={_pb_w_pt:.0f} h={_pb_h_pt:.0f} — cleared")
                bx1 = by1 = bx2 = by2 = None
                length_ft = 0.0

        # ── Structural depth-to-span sanity check ────────────────────────────
        # Research (AISC / Steel Beam Span Guide) confirms:
        #   • W12X16 (lightest W12) realistic max span = 10–14 ft normal loads
        #   • Practical L/d ratio for W-shapes ≤ 30–35 under light roof loads
        #   • Any W12 beam spanning 87 ft is physically impossible
        #
        # Rule: max_span_ft = nominal_depth_inches × 4
        #   W12 → 48 ft   W16 → 64 ft   W24 → 96 ft   W36 → 144 ft
        # This catches impossible matches (W12X16 @ 132ft from a false line/grid
        # match) while keeping all legitimate long-span girders (W36, W40, plate
        # girders).  Applies to every depth-named beam section — W, rectangular
        # HSS, and C/MC channels (a C8 channel can never span 83 ft; those are
        # always false matches to grid / border / dimension lines).  The depth is
        # the first number in the name (W16X.. / HSS16X4.. / C8X11 / MC12X31).
        if bx1 is not None and mtype == "beam" and length_ft > 0:
            _depth_match = re.match(r'(?:W|HSS|MC|C)(\d{1,2})', str(p.get("profile") or ""), re.IGNORECASE)
            if _depth_match:
                _nom_depth = int(_depth_match.group(1))
                _max_span_ft = _nom_depth * 6     # realistic upper bound (L/d ~72)
                if length_ft > _max_span_ft:
                    print(f"[BUILD] Section-depth check failed: {p['profile']} "
                          f"span={length_ft:.1f}ft > max={_max_span_ft}ft "
                          f"(depth={_nom_depth}in × 6) — cleared")
                    bx1 = by1 = bx2 = by2 = None
                    length_ft = 0.0

        # Heavy section minimum span check: W24-W40 members must span at least 10 ft
        # This drops false matches to callout borders, detail bubbles, or stair leader lines.
        if bx1 is not None and mtype == "beam" and length_ft > 0:
            _heavy_match = re.match(r'W(2[4-9]|3[0-9]|4[0-9])', (p.get("profile") or ""), re.IGNORECASE)
            if _heavy_match and length_ft < 10.0:
                print(f"[BUILD] Heavy section span too short for {p['profile']} (L={length_ft:.1f}ft < 10ft) — dropped false note leader")
                bx1 = by1 = bx2 = by2 = None
                length_ft = 0.0

        sym = profile_sym_pos.get(p_idx)

        # Stage 3 (2026-07-17 rebuild, live-verified against real SteelGenie
        # foundation plans): only treat this as a footing/column split when
        # the profile is STILL symbol-matched at this point (the beam-line
        # and section-type overrides above call
        # symbol_matched_cols.discard(p_idx) when they reclassify a false
        # column match back to a beam -- checking membership here, not just
        # profile_sym_idx, is what keeps those overrides authoritative).
        _sym_idx = profile_sym_idx.get(p_idx) if p_idx in symbol_matched_cols else None
        _sym_category = (
            column_symbols[_sym_idx].get("category")
            if (_sym_idx is not None and column_symbols) else None
        )

        if mtype == "column" and _sym_category == "footing_isolated":
            import uuid as _uuid_mod
            _linked_group_id = str(_uuid_mod.uuid4())
            members.append({
                "profile":   None,
                "type":      "footing",
                "length_ft": 0.0,
                "beam_dir":  None,
                "bx1": None, "by1": None, "bx2": None, "by2": None,
                "x":  round(render_cx / page_w, 4),
                "y":  round(render_cy / page_h, 4),
                "lx": round(p["cx"] / page_w, 4),
                "ly": round(p["cy"] / page_h, 4),
                "sx": sym[0] if sym else None,
                "sy": sym[1] if sym else None,
                "w":  0.03, "h": 0.03,
                "color":     MEMBER_COLORS.get("footing", "#6B7280"),
                "confirmed": True,
                "is_column": False,
                "geometry": {"category": _sym_category, "linked_group_id": _linked_group_id, "linked_role": "footing"},
            })
        else:
            _linked_group_id = None

        is_unlabeled = bool(p.get('unlabeled') or p.get('profile') == '?')
        members.append({
            'profile':   None if is_unlabeled else p['profile'],
            'type':      mtype,
            'length_ft': length_ft,
            'beam_dir':  beam_dir,
            'bx1': bx1, 'by1': by1,
            'bx2': bx2, 'by2': by2,
            'x':  round(render_cx / page_w, 4),
            'y':  round(render_cy / page_h, 4),
            'lx': round(p['cx'] / page_w, 4),
            'ly': round(p['cy'] / page_h, 4),
            'sx': sym[0] if sym else None,
            'sy': sym[1] if sym else None,
            'w':  0.025, 'h': 0.012,
            'color':     MEMBER_COLORS.get('unlabeled' if is_unlabeled else mtype, '#6B7280'),
            'confirmed': not is_unlabeled,
            'is_column': mtype == 'column',
            'unlabeled': is_unlabeled,
            'geometry': {
                **({'category': _sym_category, 'linked_group_id': _linked_group_id, 'linked_role': 'column' if _linked_group_id else None} if _sym_category else {}),
                'unlabeled': is_unlabeled,
            },
        })
    # ── Post-processing: drop unlabeled beam stubs & grid lines ──────────────
    members = [m for m in members if not (m.get("type") == "beam" and (not m.get("profile") or m.get("profile") == "?"))]

    # ── Post-processing: remove duplicates and short stubs ───────────────────
    #
    # 1. SHORT-STUB FILTER: beams under 5 ft are annotation ticks, hatch
    #    stubs, or callout leaders — never structural members.
    #
    # 2. DUPLICATE-SPAN FILTER: when multiple profile labels sit on (or very
    #    near) the same structural centreline they each independently match
    #    the same vector segment.  The result is 2-4 identical span entries
    #    for one physical beam.  We group by span endpoints (rounded to 4 pt
    #    ≈ 0.5" tolerance) and keep only the entry whose profile appears most
    #    frequently in the group (plurality vote); ties go to the heaviest
    #    section (highest weight-per-foot digit in the name).
    MIN_BEAM_FT = 1.0     # structural beams can be short framing stubs
    SPAN_TOL_PT = 8       # round endpoints to this many pts before grouping

    filtered = []
    for mem in members:
        # Always keep columns, braces, footings
        if mem["type"] not in ("beam", "joist"):
            filtered.append(mem)
            continue
        # Drop orphaned text callouts with no drawn span line or stubs < MIN_BEAM_FT
        if mem.get("bx1") is None or mem.get("length_ft", 0) < MIN_BEAM_FT:
            continue
        filtered.append(mem)

    # Group beams and joists by quantised span key
    from collections import Counter
    span_groups: dict = {}   # key → list of (index, member)
    no_span_beams = []
    for i, mem in enumerate(filtered):
        if mem["type"] not in ("beam", "joist") or mem.get("bx1") is None:
            no_span_beams.append(mem)
            continue
        bx1r = round(mem["bx1"] * page_w / SPAN_TOL_PT)
        by1r = round(mem["by1"] * page_h / SPAN_TOL_PT)
        bx2r = round(mem["bx2"] * page_w / SPAN_TOL_PT)
        by2r = round(mem["by2"] * page_h / SPAN_TOL_PT)
        # Normalise direction and partition by type so joists and beams never clobber each other
        key = (mem["type"], min(bx1r, bx2r), min(by1r, by2r), max(bx1r, bx2r), max(by1r, by2r))
        span_groups.setdefault(key, []).append(mem)

    deduped_beams = []
    for key, grp in span_groups.items():
        if len(grp) == 1:
            deduped_beams.append(grp[0])
            continue
        # Pick the profile that appears most often; break ties by weight digit
        prof_counts = Counter(m["profile"] for m in grp)
        best_count  = max(prof_counts.values())
        candidates  = [p for p, c in prof_counts.items() if c == best_count]
        def _weight_digit(prof):
            # Extract the weight number (after X) for tie-breaking: W24X68 → 68
            import re as _re
            wt = _re.search(r'[Xx](\d+)', str(prof or ""))
            return int(wt.group(1)) if wt else 0
        winner = max(candidates, key=_weight_digit)
        # Keep the first member in the group that has the winning profile
        keeper = next((m for m in grp if m["profile"] == winner), grp[0])
        deduped_beams.append(keeper)
        if len(grp) > 1:
            dropped = [m["profile"] for m in grp if m is not keeper]
            print(f"[DEDUP] Merged {len(grp)} beams at same span -> kept {winner}, "
                  f"dropped {dropped}")

    # ── 3. PARALLEL-OVERLAP DEDUP ─────────────────────────────────────────────
    # The exact-span grouping above only catches IDENTICAL spans.  CAD drawings
    # often draw a beam centreline twice (e.g. centreline + an adjacent flange/
    # wall-face line), producing two same-profile spans that are parallel and
    # overlapping but a few pt apart — they render as a doubled line with two
    # stacked chips.  Merge them: keep the longer span, drop the shorter.
    # Strict gate (same profile, near-parallel, perp gap ≤ 20 pt ≈ 2.2 ft,
    # real axial overlap) ensures genuine adjacent beams are never merged.
    def _seg_pt(m):
        return (m["bx1"] * page_w, m["by1"] * page_h,
                m["bx2"] * page_w, m["by2"] * page_h)

    def _is_parallel_overlap(a, b):
        ax1, ay1, ax2, ay2 = _seg_pt(a)
        bx1p, by1p, bx2p, by2p = _seg_pt(b)
        aL = math.hypot(ax2 - ax1, ay2 - ay1)
        bL = math.hypot(bx2p - bx1p, by2p - by1p)
        if aL < 1 or bL < 1:
            return False
        ux, uy = (ax2 - ax1) / aL, (ay2 - ay1) / aL
        # Parallel? (direction dot ≥ cos16° ≈ 0.96)
        if abs(((bx2p - bx1p) * ux + (by2p - by1p) * uy) / bL) < 0.96:
            return False
        # Perpendicular gap from B-midpoint to A's line
        mx, my = (bx1p + bx2p) / 2, (by1p + by2p) / 2
        perp = abs((mx - ax1) * (-uy) + (my - ay1) * ux)
        # Length ratio and axial overlap fraction (of the shorter segment)
        lr = min(aL, bL) / max(aL, bL)
        tb1 = (bx1p - ax1) * ux + (by1p - ay1) * uy
        tb2 = (bx2p - ax1) * ux + (by2p - ay1) * uy
        lo, hi = max(0.0, min(tb1, tb2)), min(aL, max(tb1, tb2))
        ovr = (hi - lo) / min(aL, bL)

        # Path 1 — DOUBLED LINE: same beam drawn a few pt apart (centreline +
        # flange/wall-face line).  Needs near-equal length and heavy overlap.
        if perp <= 20 and lr >= 0.7 and ovr >= 0.7:
            return True

        # Path 2 — COLLINEAR DUPLICATE: two same-profile spans on essentially the
        # SAME line (perp ≤ 4 pt) that overlap.  Two physically distinct beams are
        # never on the exact same centreline AND overlapping, so this is always a
        # duplicate detection — even when overlap/length differ moderately.
        # The lr ≥ 0.5 floor still protects a genuine short beam that merely runs
        # along part of a long girder (extreme length mismatch).
        if perp <= 4.0 and lr >= 0.5 and ovr >= 0.5:
            return True

        return False

    _po_kept = []
    _po_dropped = 0
    for mem in deduped_beams:
        dup_of = None
        for k in _po_kept:
            if k["profile"] == mem["profile"] and _is_parallel_overlap(k, mem):
                dup_of = k
                break
        if dup_of is None:
            _po_kept.append(mem)
        else:
            # keep whichever has the longer drawn span
            if mem.get("length_ft", 0) > dup_of.get("length_ft", 0):
                _po_kept[_po_kept.index(dup_of)] = mem
            _po_dropped += 1
    if _po_dropped:
        print(f"[DEDUP] Parallel-overlap pass removed {_po_dropped} doubled beam(s)")
    deduped_beams = _po_kept

    # `no_span_beams` already contains every non-beam member (columns, braces,
    # footings) -- the loop above stashes it there via the
    # `mem["type"] != "beam" or mem.get("bx1") is None` condition, which is
    # true for ALL of them regardless of span. Re-adding
    # `[m for m in filtered if m["type"] != "beam"]` here duplicated every
    # single column (and brace/footing) a second time at its exact rendered
    # position -- this is what produced an extra phantom column stacked on
    # top of every real one on framing/roof plans (columns are gated purely
    # by type here, not by anything page-specific, so the duplication hit
    # every drawing, not just this one).
    deduped = deduped_beams + no_span_beams
    print(f"[DEDUP] {len(members)} -> {len(deduped)} members "
          f"({len(members)-len(deduped)} removed)")
    return deduped


def dedup_overlapping_beams(members, page_w, page_h, pts_per_foot):
    """Remove duplicate beam overlays left after the labeled + unlabeled passes.

    1. Multi-bay composite line removal:
       A continuous drawn line (e.g. wall or CMU infill face) that extends across
       multiple bays parallel to and directly overlapping 2 or more shorter bay beams
       (e.g. W16x26 10.8' and W12x19 13.7') is a drawing artifact and must be dropped.
    2. Parallel doubled beam detection:
       Two beams that are parallel, along the same framing corridor (within ~2.5-3.5 ft)
       and overlap significantly (>= 70%) represent the same physical member drawn or
       detected twice. Keeps the primary structural member, dropping secondary note
       matches (e.g. elevation tags '(+32.46)' or '(LO)') and unlabeled duplicates.
    """
    ppf  = pts_per_foot if pts_per_foot > 0 else 9.0
    CORRIDOR_TOL = max(32.0, ppf * 3.5)
    NEAR_TOL     = max(20.0, ppf * 2.2)

    beams = [m for m in members
             if m.get("type") == "beam" and m.get("bx1") is not None]

    def geo(m):
        return (m["bx1"] * page_w, m["by1"] * page_h,
                m["bx2"] * page_w, m["by2"] * page_h)

    drop = set()

    # Pass 1: Multi-bay composite duplicate removal
    for i in range(len(beams)):
        if id(beams[i]) in drop:
            continue
        ax1, ay1, ax2, ay2 = geo(beams[i])
        La = math.hypot(ax2 - ax1, ay2 - ay1) or 1.0
        ux, uy = (ax2 - ax1) / La, (ay2 - ay1) / La
        px, py = -uy, ux

        contained = []
        for j in range(len(beams)):
            if i == j or id(beams[j]) in drop:
                continue
            bx1, by1, bx2, by2 = geo(beams[j])
            Lb = math.hypot(bx2 - bx1, by2 - by1) or 1.0
            if abs(((bx2 - bx1) * ux + (by2 - by1) * uy) / Lb) < 0.96:
                continue
            perp_dist = abs((bx1 - ax1) * px + (by1 - ay1) * py)
            if perp_dist > CORRIDOR_TOL:
                continue
            t1 = (bx1 - ax1) * ux + (by1 - ay1) * uy
            t2 = (bx2 - ax1) * ux + (by2 - ay1) * uy
            lo, hi = min(t1, t2), max(t1, t2)
            ovr = min(La, hi) - max(0.0, lo)
            if ovr >= 0.70 * Lb:
                contained.append((j, beams[j], Lb, lo, hi))

        if len(contained) >= 2:
            tot_cov = sum(cb[2] for cb in contained)
            if tot_cov >= 0.70 * La and any(cb[2] < 0.75 * La for cb in contained):
                drop.add(id(beams[i]))

    # Pass 2: Parallel duplicate beams on same corridor (near-equal or heavy overlap)
    for i in range(len(beams)):
        if id(beams[i]) in drop:
            continue
        ax1, ay1, ax2, ay2 = geo(beams[i])
        La = math.hypot(ax2 - ax1, ay2 - ay1) or 1.0
        ux, uy = (ax2 - ax1) / La, (ay2 - ay1) / La
        px, py = -uy, ux

        for j in range(len(beams)):
            if i == j or id(beams[j]) in drop:
                continue
            bx1, by1, bx2, by2 = geo(beams[j])
            Lb = math.hypot(bx2 - bx1, by2 - by1) or 1.0
            if abs(((bx2 - bx1) * ux + (by2 - by1) * uy) / Lb) < 0.96:
                continue
            perp_dist = abs((bx1 - ax1) * px + (by1 - ay1) * py)
            if perp_dist > NEAR_TOL:
                continue
            t1 = (bx1 - ax1) * ux + (by1 - ay1) * uy
            t2 = (bx2 - ax1) * ux + (by2 - ay1) * uy
            lo, hi = min(t1, t2), max(t1, t2)
            ovr = min(La, hi) - max(0.0, lo)
            if ovr < 0.75 * min(La, Lb):
                continue

            ai = not beams[i].get("unlabeled")
            bj = not beams[j].get("unlabeled")
            if ai and not bj:
                drop.add(id(beams[j]))
            elif bj and not ai:
                drop.add(id(beams[i]))
                break
            elif (not ai) and (not bj):
                drop.add(id(beams[j]) if La >= Lb else id(beams[i]))
                if id(beams[i]) in drop:
                    break
            else:
                # Both labeled: check for note tags like (+...), (LO), (TYP)
                p_i = str(beams[i].get("profile", ""))
                p_j = str(beams[j].get("profile", ""))
                has_note_i = any(k in p_i for k in ["(+", "(LO", "TYP"])
                has_note_j = any(k in p_j for k in ["(+", "(LO", "TYP"])
                if has_note_i and not has_note_j:
                    drop.add(id(beams[i]))
                    break
                elif has_note_j and not has_note_i:
                    drop.add(id(beams[j]))
                elif abs(La - Lb) / max(La, Lb) < 0.25:
                    drop.add(id(beams[j]) if La >= Lb else id(beams[i]))
                    if id(beams[i]) in drop:
                        break

    if drop:
        print(f"[DEDUP] removed {len(drop)} duplicate overlapping beam overlay(s)")
    return [m for m in members if id(m) not in drop]


# ── Steel weight (lb/ft) ──────────────────────────────────────────────────────
# W / C / MC / S / HP / WT / MT / ST designations ENCODE the nominal weight as
# the number after the last 'X' (e.g. W12X19 = 19 lb/ft, C12X20.7 = 20.7 lb/ft),
# so no table is needed for them.  HSS / L / PIPE designations are DIMENSIONAL,
# so their weights come from a small AISC lookup (extend as needed).
# ── AISC 15th & 16th Edition Official Weight Tables (Table 1-11, 1-12, 1-7) ──
_DIM_SHAPE_WT = {
    # ── Square HSS (AISC Table 1-12) ──
    "HSS16X16X5/8": 127.40, "HSS16X16X1/2": 103.30, "HSS16X16X3/8": 78.60,
    "HSS14X14X5/8": 110.40, "HSS14X14X1/2": 89.68, "HSS14X14X3/8": 68.37,
    "HSS12X12X5/8": 93.36, "HSS12X12X1/2": 76.07, "HSS12X12X3/8": 58.10, "HSS12X12X5/16": 49.00, "HSS12X12X1/4": 39.43,
    "HSS10X10X5/8": 76.34, "HSS10X10X1/2": 62.46, "HSS10X10X3/8": 47.90, "HSS10X10X5/16": 40.35, "HSS10X10X1/4": 32.63,
    "HSS8X8X5/8": 59.32, "HSS8X8X1/2": 47.35, "HSS8X8X3/8": 37.69, "HSS8X8X5/16": 31.84, "HSS8X8X1/4": 25.82, "HSS8X8X3/16": 19.63,
    "HSS7X7X1/2": 42.05, "HSS7X7X3/8": 32.58, "HSS7X7X5/16": 27.59, "HSS7X7X1/4": 22.42,
    "HSS6X6X5/8": 42.30, "HSS6X6X1/2": 35.05, "HSS6X6X3/8": 27.48, "HSS6X6X5/16": 23.34, "HSS6X6X1/4": 19.02, "HSS6X6X3/16": 14.53,
    "HSS5X5X1/2": 28.25, "HSS5X5X3/8": 22.37, "HSS5X5X5/16": 19.08, "HSS5X5X1/4": 15.62, "HSS5X5X3/16": 11.97,
    "HSS4X4X1/2": 21.46, "HSS4X4X3/8": 17.27, "HSS4X4X5/16": 14.83, "HSS4X4X1/4": 12.21, "HSS4X4X3/16": 9.42, "HSS4X4X1/8": 6.46,
    "HSS3.5X3.5X1/4": 10.51, "HSS3.5X3.5X3/16": 8.15,
    "HSS3X3X3/8": 12.17, "HSS3X3X5/16": 10.58, "HSS3X3X1/4": 8.81, "HSS3X3X3/16": 6.87,
    "HSS2.5X2.5X1/4": 7.11, "HSS2.5X2.5X3/16": 5.59,
    "HSS2X2X1/4": 5.41, "HSS2X2X3/16": 4.32, "HSS2X2X1/8": 3.05,

    # ── Rectangular HSS (AISC Table 1-11) ──
    "HSS16X12X5/8": 110.40, "HSS16X12X1/2": 89.68, "HSS16X12X3/8": 68.37,
    "HSS16X8X1/2": 76.07, "HSS16X8X3/8": 58.10,
    "HSS14X10X1/2": 76.07, "HSS14X10X3/8": 58.10,
    "HSS14X6X1/2": 62.46, "HSS14X6X3/8": 47.90,
    "HSS12X10X1/2": 69.26, "HSS12X10X3/8": 53.00,
    "HSS12X8X5/8": 76.34, "HSS12X8X1/2": 62.46, "HSS12X8X3/8": 47.90, "HSS12X8X5/16": 40.35, "HSS12X8X1/4": 32.63,
    "HSS12X6X1/2": 55.66, "HSS12X6X3/8": 42.79, "HSS12X6X5/16": 36.10, "HSS12X6X1/4": 29.23,
    "HSS12X4X3/8": 37.69, "HSS12X4X1/4": 25.82,
    "HSS10X8X1/2": 55.66, "HSS10X8X3/8": 42.79, "HSS10X8X5/16": 36.10, "HSS10X8X1/4": 29.23,
    "HSS10X6X1/2": 47.35, "HSS10X6X3/8": 37.69, "HSS10X6X5/16": 31.84, "HSS10X6X1/4": 25.82,
    "HSS10X4X3/8": 32.58, "HSS10X4X5/16": 27.59, "HSS10X4X1/4": 22.42,
    "HSS8X6X1/2": 42.05, "HSS8X6X3/8": 32.58, "HSS8X6X5/16": 27.59, "HSS8X6X1/4": 22.42,
    "HSS8X4X1/2": 35.05, "HSS8X4X3/8": 27.48, "HSS8X4X5/16": 23.34, "HSS8X4X1/4": 19.02, "HSS8X4X3/16": 14.53,
    "HSS6X4X1/2": 28.25, "HSS6X4X3/8": 22.37, "HSS6X4X5/16": 19.08, "HSS6X4X1/4": 15.62, "HSS6X4X3/16": 11.97,
    "HSS6X3X3/8": 19.82, "HSS6X3X1/4": 13.92,
    "HSS6X2X1/4": 12.21,
    "HSS5X3X3/8": 17.27, "HSS5X3X1/4": 12.21,
    "HSS4X3X3/8": 14.72, "HSS4X3X1/4": 10.51,
    "HSS4X2X1/4": 8.81, "HSS4X2X3/16": 6.87,

    # ── Angles (AISC Table 1-7) ──
    "L8X8X1": 51.0, "L8X8X7/8": 45.0, "L8X8X3/4": 38.9, "L8X8X5/8": 32.8, "L8X8X1/2": 26.4,
    "L6X6X1": 37.4, "L6X6X7/8": 33.1, "L6X6X3/4": 28.7, "L6X6X5/8": 24.2, "L6X6X1/2": 19.6, "L6X6X3/8": 14.9,
    "L5X5X7/8": 27.2, "L5X5X3/4": 23.6, "L5X5X5/8": 20.0, "L5X5X1/2": 16.2, "L5X5X3/8": 12.3, "L5X5X5/16": 10.3,
    "L4X4X3/4": 18.5, "L4X4X5/8": 15.7, "L4X4X1/2": 12.8, "L4X4X3/8": 9.8, "L4X4X5/16": 8.2, "L4X4X1/4": 6.6,
    "L3.5X3.5X1/2": 11.1, "L3.5X3.5X3/8": 8.5, "L3.5X3.5X1/4": 5.8,
    "L3X3X1/2": 9.4, "L3X3X3/8": 7.2, "L3X3X5/16": 6.1, "L3X3X1/4": 4.9, "L3X3X3/16": 3.71,
    "L2.5X2.5X3/8": 5.9, "L2.5X2.5X5/16": 5.0, "L2.5X2.5X1/4": 4.1, "L2.5X2.5X3/16": 3.07,
    "L2X2X3/8": 4.7, "L2X2X5/16": 3.92, "L2X2X1/4": 3.19, "L2X2X3/16": 2.44, "L2X2X1/8": 1.65,
}

# ── Dynamic Master AISC Database Loader ──
_AISC_JSON_PATH = os.path.join(os.path.dirname(__file__), "data", "aisc_v16_shapes.json")
if os.path.exists(_AISC_JSON_PATH):
    try:
        with open(_AISC_JSON_PATH, "r", encoding="utf-8") as _f:
            _ext_db = json.load(_f)
            for _k, _v in _ext_db.items():
                if isinstance(_v, dict) and "weight_lb_ft" in _v:
                    _DIM_SHAPE_WT[_k] = float(_v["weight_lb_ft"])
            print(f"[AISC] Loaded {len(_ext_db)} shapes from external AISC database")
    except Exception as _e:
        print(f"[AISC] Error loading external database: {_e}")

_THICKNESS_DECIMAL_MAP = {
    0.125: "1/8", 0.1875: "3/16", 0.188: "3/16",
    0.25: "1/4", 0.250: "1/4",
    0.3125: "5/16", 0.312: "5/16", 0.313: "5/16",
    0.375: "3/8",
    0.5: "1/2", 0.500: "1/2",
    0.625: "5/8",
    0.75: "3/4", 0.750: "3/4",
    0.875: "7/8",
    1.0: "1", 1.000: "1",
}

def profile_weight_per_ft(profile):
    """Nominal weight in lb/ft for an AISC structural steel section label (AISC 15 & 16)."""
    p = (profile or "").upper().strip().replace(" ", "").replace("×", "X")
    if not p:
        return None
    
    # 1. Self-encoding standard profiles: [Shape][Depth]X[Weight_lb_ft]
    #    e.g. W16X31 -> 31 lb/ft, W24X84 -> 84 lb/ft, C12X20.7 -> 20.7 lb/ft, WT8X15.5 -> 15.5 lb/ft
    m = re.match(r'^(?:W|C|MC|S|HP|WT|MT|ST|M)\d+(?:\.\d+)?X(\d+(?:\.\d+)?)$', p)
    if m:
        return float(m.group(1))

    # 2. Normalize decimal thicknesses in HSS / L keys (e.g. HSS8X8X.500 -> HSS8X8X1/2)
    norm_p = p
    hss_dec = re.match(r'^(HSS|2?L)(\d+(?:\.\d+)?X\d+(?:\.\d+)?X)(0?\.\d+)$', p)
    if hss_dec:
        prefix, dims, dec_str = hss_dec.group(1), hss_dec.group(2), float(hss_dec.group(3))
        # Find closest standard thickness
        best_frac = None
        for dec_val, frac_str in _THICKNESS_DECIMAL_MAP.items():
            if abs(dec_str - dec_val) < 0.015:
                best_frac = frac_str
                break
        if best_frac:
            norm_p = f"{prefix}{dims}{best_frac}"

    # 3. Known AISC 15 & 16 Table 1-11 / 1-12 / 1-7 lookup
    if norm_p in _DIM_SHAPE_WT:
        return _DIM_SHAPE_WT[norm_p]
    if p in _DIM_SHAPE_WT:
        return _DIM_SHAPE_WT[p]

    # 4. Dynamic HSS weight calculation (AISC formula with corner radius deduction)
    hss_match = re.match(r'^HSS(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)X([\d/]+|\d+\.\d+)$', p)
    if hss_match:
        try:
            h = float(hss_match.group(1))
            w = float(hss_match.group(2))
            t_str = hss_match.group(3)
            t = (float(t_str.split('/')[0]) / float(t_str.split('/')[1])) if '/' in t_str else float(t_str)
            # AISC Exact Corner-Radius Adjusted Area Formula
            # Outside radius Ro = 2.25 * t, Inside radius Ri = 1.25 * t
            # Area = 2*t*(h + w - 2*t) - (4 - pi)*(2*t^2)
            area = 2.0 * t * (h + w - 2.0 * t) - 0.8584 * (t ** 2)
            # Steel density = 3.4 lb/(ft * in^2)
            return round(area * 3.4, 2)
        except Exception:
            pass

    # 5. Dynamic Angle (L) weight calculation
    l_match = re.match(r'^(2?L)(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)X([\d/]+|\d+\.\d+)$', p)
    if l_match:
        try:
            is_double = l_match.group(1).startswith('2')
            l1 = float(l_match.group(2))
            l2 = float(l_match.group(3))
            t_str = l_match.group(4)
            t = (float(t_str.split('/')[0]) / float(t_str.split('/')[1])) if '/' in t_str else float(t_str)
            area = (l1 + l2 - t) * t
            wt = area * 3.4
            if is_double:
                wt *= 2.0
            return round(wt, 2)
        except Exception:
            pass

    return None


def build_summary(members):
    s = {
        "column": 0, "beam": 0,
        "vertical_brace": 0, "horizontal_brace": 0,
        "joists": 0, "moment_connection": 0, "default_connection": 0,
        "bolt": 0, "camber": 0, "anchor": 0,
        "weld_studs": 0, "total_weight_tons": 0,
    }
    total_lb   = 0.0     # weight of SIZED members (length × lb/ft)
    weighed_ft = 0.0     # length of members we could weigh
    unsized_ft = 0.0     # length of beams with no known size (e.g. unlabeled)
    for m in members:
        t = m.get("type", "beam")
        if   t == "column":                      s["column"] += 1
        elif t == "beam":                         s["beam"]   += 1
        elif t == "joist":                        s["joists"] += 1
        elif t in ("brace", "vertical_brace"):    s["vertical_brace"] += 1
        elif t == "horizontal_brace":             s["horizontal_brace"] += 1

        # Tonnage from any member that carries a length AND a sized profile.
        if t in ("beam", "brace", "vertical_brace", "horizontal_brace"):
            L = m.get("length_ft", 0) or 0.0
            if L > 0:
                w = profile_weight_per_ft((m.get("profile") or ""))
                if w:
                    total_lb   += w * L
                    weighed_ft += L
                else:
                    unsized_ft += L

    s["total_weight_tons"] = round(total_lb / 2000.0, 2)
    s["weighed_length_ft"] = round(weighed_ft, 1)
    s["unsized_length_ft"] = round(unsized_ft, 1)
    return s


def add_unlabeled_beam_candidates(members, all_lines, v_grid, h_grid,
                                  plan_bounds, page_w, page_h, pts_per_foot,
                                  column_symbols=None):
    """Detect unlabeled beams using DOUBLE-LINE PAIR detection.

    Every beam — labeled or not — is drawn as TWO parallel lines representing
    the top and bottom flanges of the I/W section.  Detecting a MATCHED PAIR
    of parallel lines at beam-depth spacing is a far stronger structural signal
    than any single-line heuristic:
      • dimension lines  → single line only (no matching parallel flange)
      • wall lines       → pair too close together (< W6 depth) or too far
      • curtain-wall     → boundary lines, no matching parallel at beam depth
      • stair hatch      → many closely-spaced parallels, not a clean pair
      • real beam        → exactly TWO parallel lines at section-depth spacing

    Pipeline:
      1. Bucket all solid lines into H-lines and V-lines (structural length only).
      2. For every pair within MIN_DEPTH…MAX_DEPTH spacing:
           – significant length overlap (≥ 50 % of shorter line)
           – similar lengths (within 35 %)
      3. Pair centerline = candidate beam position.
      4. Column at BOTH endpoints (augmented-grid test, shape-independent).
      5. Not already covered by a labeled beam.
      6. Not at the building edge (boundary / curtain-wall lines).
      7. Dedup — one candidate per spatial slot.
    """
    if not all_lines or not plan_bounds:
        return members

    ppf = pts_per_foot if pts_per_foot > 0 else 9.0
    pb0x, pb0y, pb1x, pb1y = plan_bounds
    plan_w, plan_h = pb1x - pb0x, pb1y - pb0y

    MIN_FT, MAX_FT = 5.0, 70.0
    GRID_TOLP = 6.0
    COL_TOL   = 40.0

    # Beam section depth at this scale (flange-to-flange pt distance).
    # W6 ≈ 6 in deep, W36 ≈ 36 in deep; convert to pts at current ppf.
    MIN_DEPTH = max(4.0,  ppf * (6.0  / 12.0))   # ~ W6  minimum
    MAX_DEPTH = min(65.0, ppf * (36.0 / 12.0))   # ~ W36 maximum
    OVERLAP_RATIO = 0.50   # flange lines must overlap ≥ 50 % of shorter line
    LEN_RATIO     = 1.35   # lengths must be within 35 % of each other

    # ── labeled-beam data ──────────────────────────────────────────────────────
    lab = [(m["bx1"]*page_w, m["by1"]*page_h,
            m["bx2"]*page_w, m["by2"]*page_h)
           for m in members
           if m.get("type") == "beam" and m.get("bx1") is not None]
    cols = [(m["x"]*page_w, m["y"]*page_h)
            for m in members if m.get("type") == "column"]
    lab_ends = []
    for (a, b, c, d) in lab:
        lab_ends += [(a, b), (c, d)]

    # ── augmented grid (covers edge zones where bubbles aren't drawn) ──────────
    def _cluster(vals, tol=9.0, minn=2):
        out, cur = [], []
        for v in sorted(vals):
            if not cur or v - cur[-1] <= tol:
                cur.append(v)
            else:
                if len(cur) >= minn:
                    out.append(sum(cur) / len(cur))
                cur = [v]
        if cur and len(cur) >= minn:
            out.append(sum(cur) / len(cur))
        return out

    # Raw symbol positions (ALL 88 detected — before emit_symbol_columns filter).
    # emit_symbol_columns drops symbols with no beam framing into them, so
    # fractional-row columns (e.g. B.2 row) and edge-zone columns that were
    # DETECTED but not EMITTED are invisible to the aug grids without this.
    # Adding them directly (no clustering — each is an exact column position)
    # closes the gap for:
    #   • Fractional grid rows  (B.2, C.6, D.1, D.2, E.4 …)
    #   • Right/left-edge columns whose beams haven't been emitted yet
    _raw_sym_x = [s["cx"] for s in (column_symbols or [])]
    _raw_sym_y = [s["cy"] for s in (column_symbols or [])]

    aug_vx = sorted(set(list(v_grid or [])
                        + _cluster([e[0] for e in lab_ends])
                        + _cluster([cx for cx, _ in cols])
                        + _raw_sym_x))
    aug_hy = sorted(set(list(h_grid or [])
                        + _cluster([e[1] for e in lab_ends])
                        + _cluster([cy for _, cy in cols])
                        + _raw_sym_y))

    def _has_col(ex, ey):
        # Primary: aug grid intersection (tight 18 pt tolerance)
        if aug_vx and aug_hy and \
           min(abs(ex-g) for g in aug_vx) < 18.0 and \
           min(abs(ey-g) for g in aug_hy) < 18.0:
            return True
        # Secondary: emitted column member position
        if any(math.hypot(ex-cx, ey-cy) < COL_TOL for cx, cy in cols):
            return True
        # Tertiary: direct raw symbol proximity — catches symbols that were
        # detected but not emitted (no beam framing yet at time of check).
        # Uses COL_TOL (40 pt) — same radius as the emitted-column check.
        if any(math.hypot(ex-s["cx"], ey-s["cy"]) < COL_TOL
               for s in (column_symbols or [])):
            return True
        return sum(1 for bx, by in lab_ends
                   if math.hypot(ex-bx, ey-by) < COL_TOL) >= 2

    def _covered(lx1, ly1, lx2, ly2):
        """True if this centerline overlaps a labeled beam (already extracted)."""
        L = math.hypot(lx2-lx1, ly2-ly1) or 1.0
        ux, uy = (lx2-lx1)/L, (ly2-ly1)/L
        for (ax1, ay1, ax2, ay2) in lab:
            aL = math.hypot(ax2-ax1, ay2-ay1) or 1.0
            if abs(((ax2-ax1)*ux + (ay2-ay1)*uy) / aL) < 0.96:
                continue
            if abs((ax1-lx1)*(-uy) + (ay1-ly1)*ux) > 18:
                continue
            t1 = (ax1-lx1)*ux + (ay1-ly1)*uy
            t2 = (ax2-lx1)*ux + (ay2-ly1)*uy
            if min(L, max(t1, t2)) - max(0.0, min(t1, t2)) > 0.40*L:
                return True
        return False

    # ── 1. bucket lines into H and V ──────────────────────────────────────────
    # H bucket: (x_start, x_end, y_mid, length, width)
    # V bucket: (x_mid, y_start, y_end, length, width)
    h_segs, v_segs = [], []
    for (x1, y1, x2, y2, ln, wv) in all_lines:
        Lft = ln / ppf
        if Lft < MIN_FT or Lft > MAX_FT:
            continue
        adx, ady = abs(x2-x1), abs(y2-y1)
        if adx > ady * 2:                          # horizontal
            if adx > plan_w * 0.85: continue       # full-width border → skip
            if x1 > x2: x1, y1, x2, y2 = x2, y2, x1, y1
            ym = (y1+y2) / 2
            if h_grid and min(abs(ym-g) for g in h_grid) < GRID_TOLP:
                continue                            # ON a grid row → skip
            h_segs.append((x1, x2, ym, ln, wv))
        elif ady > adx * 2:                        # vertical
            if ady > plan_h * 0.85: continue
            if y1 > y2: x1, y1, x2, y2 = x2, y2, x1, y1
            xm = (x1+x2) / 2
            if v_grid and min(abs(xm-g) for g in v_grid) < GRID_TOLP:
                continue
            v_segs.append((xm, y1, y2, ln, wv))

    # ── 2. find matched flange pairs ──────────────────────────────────────────
    raw_pairs = []   # (cx1, cy1, cx2, cy2, cln, bdir)

    # Horizontal pairs — sort by y_mid, scan upward within MAX_DEPTH
    h_by_y = sorted(h_segs, key=lambda s: s[2])
    for i, (axs, axe, ay, aln, _aw) in enumerate(h_by_y):
        for j in range(i+1, len(h_by_y)):
            bxs, bxe, by, bln, _bw = h_by_y[j]
            dy = by - ay
            if dy > MAX_DEPTH: break
            if dy < MIN_DEPTH: continue
            # At least one flange must be a real structural line.
            # Annotation/dimension/hatch lines are hairline (< 0.25 pt);
            # beam flanges are always >= 0.3 pt.  Two hairlines = false pair.
            if max(_aw, _bw) < 0.3: continue
            ovlp = min(axe, bxe) - max(axs, bxs)
            if ovlp < OVERLAP_RATIO * min(aln, bln): continue
            if max(aln, bln) / (min(aln, bln) or 1) > LEN_RATIO: continue
            cy  = (ay + by) / 2
            cx1 = max(axs, bxs);  cx2 = min(axe, bxe)
            cln = cx2 - cx1
            if cln / ppf < MIN_FT: continue
            raw_pairs.append((cx1, cy, cx2, cy, cln, "H"))

    # Vertical pairs — sort by x_mid, scan rightward within MAX_DEPTH
    v_by_x = sorted(v_segs, key=lambda s: s[0])
    for i, (ax, ays, aye, aln, _aw) in enumerate(v_by_x):
        for j in range(i+1, len(v_by_x)):
            bx, bys, bye, bln, _bw = v_by_x[j]
            dx = bx - ax
            if dx > MAX_DEPTH: break
            if dx < MIN_DEPTH: continue
            if max(_aw, _bw) < 0.3: continue   # hairline filter — same as H pairs
            ovlp = min(aye, bye) - max(ays, bys)
            if ovlp < OVERLAP_RATIO * min(aln, bln): continue
            if max(aln, bln) / (min(aln, bln) or 1) > LEN_RATIO: continue
            cx  = (ax + bx) / 2
            cy1 = max(ays, bys);  cy2 = min(aye, bye)
            cln = cy2 - cy1
            if cln / ppf < MIN_FT: continue
            raw_pairs.append((cx, cy1, cx, cy2, cln, "V"))

    # ── 3. filter and emit ────────────────────────────────────────────────────
    EDGE_M = COL_TOL + 8.0   # 48 pt — wider than col check so edge lines are caught
    seen, n = [], 0

    for (cx1, cy1, cx2, cy2, cln, bdir) in raw_pairs:
        mx, my = (cx1+cx2)/2, (cy1+cy2)/2
        Lft = cln / ppf

        # ── Column check FIRST ────────────────────────────────────────────────
        # A real structural beam always connects columns at BOTH endpoints.
        # Check this before edge rejection — a beam in the rightmost/leftmost
        # bay has its midpoint near the plan edge, so the old edge-first order
        # was killing real perimeter beams (circled area bug).
        # Only apply edge rejection to pairs with NO column confirmation — those
        # are curtain-wall traces, CMU boundary lines, or full-height facade
        # lines that happen to form a pair but connect to nothing structural.
        has_both_cols = _has_col(cx1, cy1) and _has_col(cx2, cy2)

        if not has_both_cols:
            # No confirmed columns → apply edge guard to keep out boundary /
            # facade lines.  With confirmed columns the beam passes even at edge.
            if bdir == "V" and aug_vx:
                vlo, vhi = min(aug_vx), max(aug_vx)
                if abs(mx-vlo) < EDGE_M or abs(mx-vhi) < EDGE_M:
                    continue
            if bdir == "H" and aug_hy:
                hlo, hhi = min(aug_hy), max(aug_hy)
                if abs(my-hlo) < EDGE_M or abs(my-hhi) < EDGE_M:
                    continue
            # No columns and not caught by edge guard → still not a beam
            continue

        # not already a labeled beam
        if _covered(cx1, cy1, cx2, cy2):
            continue

        # dedup
        if any(math.hypot(mx-sx, my-sy) < 30 for sx, sy in seen):
            continue
        seen.append((mx, my))

        members.append({
            "profile": "(beam?)", "type": "beam",
            "length_ft": round(Lft, 1),
            "beam_dir": bdir,
            "bx1": round(cx1/page_w, 4), "by1": round(cy1/page_h, 4),
            "bx2": round(cx2/page_w, 4), "by2": round(cy2/page_h, 4),
            "x":  round(mx/page_w, 4),   "y":  round(my/page_h, 4),
            "lx": round(mx/page_w, 4),   "ly": round(my/page_h, 4),
            "sx": None, "sy": None, "w": 0.025, "h": 0.012,
            "color": "#F59E0B",
            "confirmed": False, "is_column": False,
            "unlabeled": True, "confidence": "low",
        })
        n += 1

    if n:
        print(f"[UNLABELED] {n} unlabeled beam candidates (double-line pair)")

    # ── ADAPTIVE FALLBACK: single thick-centerline style ─────────────────────
    # Some CAD exports draw each beam as ONE wide stroke (not two flange lines).
    # In that case raw_pairs is empty even on a drawing with many unlabeled beams.
    # Auto-detect: if we found 0 pairs AND labeled beams exist, the drawing uses
    # single-line style → run the single-line detector with the proven filters.
    # ── auto-detect drawing style ─────────────────────────────────────────────
    # In a DOUBLE-LINE drawing, beam flanges are drawn thin (≤1.5 pt each).
    # In a SINGLE-LINE drawing, each beam is ONE thick stroke (>1.5 pt).
    # Check the max stroke weight among structural-length H lines to decide.
    _max_w = max((wv for _,_,_,_,wv in h_segs), default=0.0)
    _is_single_line = _max_w > 1.5
    print(f"[UNLABELED] style={'single-line(fallback)' if _is_single_line else 'double-line(pairs)'}  max_h_w={_max_w:.1f}pt")
    if _is_single_line and lab:
        THICK      = 0.5          # minimum stroke width for a structural line
        MIN_FT_SL  = 6.5          # raise floor: 5-6ft = wall pocket / stair trim, not framing beams
        EDGE_M2    = max(COL_TOL * 1.5, 55.0)   # wider V-edge filter (curtain wall may be slightly off max aug_vx)
        H_EDGE_TOL = GRID_TOLP * 1.5             # tight H-edge: only exact top/bottom row lines
        for (x1, y1, x2, y2, ln, wv) in all_lines:
            if wv < THICK: continue
            Lft = ln / ppf
            if Lft < MIN_FT_SL or Lft > MAX_FT: continue
            adx, ady = abs(x2-x1), abs(y2-y1)
            if adx > ady * 2:
                bdir = "H"
                if adx > plan_w * 0.85: continue
            elif ady > adx * 2:
                bdir = "V"
                if ady > plan_h * 0.85: continue
            else:
                continue
            my = (y1+y2)/2;  mx = (x1+x2)/2
            if bdir == "H" and h_grid and min(abs(my-g) for g in h_grid) < GRID_TOLP:
                continue
            if bdir == "V" and v_grid and min(abs(mx-g) for g in v_grid) < GRID_TOLP:
                continue
            # V-edge structural rule: an INTERIOR unlabeled beam has labeled
            # horizontal beams framing into it from BOTH sides (left and right).
            # A curtain-wall / boundary line only has beams from ONE side.
            # This is drawing-independent — no tolerance tuning needed.
            if bdir == "V":
                vy_lo, vy_hi = min(y1, y2), max(y1, y2)
                left_cnt  = sum(1 for ax1,ay1,ax2,ay2 in lab
                                if abs(min(ax1,ax2)-mx) < COL_TOL
                                and vy_lo-COL_TOL < (ay1+ay2)/2 < vy_hi+COL_TOL)
                right_cnt = sum(1 for ax1,ay1,ax2,ay2 in lab
                                if abs(max(ax1,ax2)-mx) < COL_TOL
                                and vy_lo-COL_TOL < (ay1+ay2)/2 < vy_hi+COL_TOL)
                if left_cnt == 0 or right_cnt == 0:
                    continue   # beams only from one side → boundary, not interior beam
            # H-edge: lines exactly ON the outermost top/bottom row are border lines
            # (use tight tolerance so interior rows at top/bottom are still kept)
            if bdir == "H" and aug_hy:
                hlo, hhi = min(aug_hy), max(aug_hy)
                if abs(my-hlo) < H_EDGE_TOL or abs(my-hhi) < H_EDGE_TOL: continue
            if not (_has_col(x1, y1) and _has_col(x2, y2)): continue
            if _covered(x1, y1, x2, y2): continue
            # No hatch filter here — column-at-both-ends is sufficient in
            # single-line mode.  The hatch filter would reject real beams near
            # other labeled beams (they appear as parallel lines within 28 pt).
            if any(math.hypot(mx-sx, my-sy) < 30 for sx, sy in seen): continue
            seen.append((mx, my))
            members.append({
                "profile": "(beam?)", "type": "beam",
                "length_ft": round(Lft, 1), "beam_dir": bdir,
                "bx1": round(x1/page_w,4), "by1": round(y1/page_h,4),
                "bx2": round(x2/page_w,4), "by2": round(y2/page_h,4),
                "x": round(mx/page_w,4),   "y": round(my/page_h,4),
                "lx": round(mx/page_w,4),  "ly": round(my/page_h,4),
                "sx": None, "sy": None, "w": 0.025, "h": 0.012,
                "color": "#F59E0B",
                "confirmed": False, "is_column": False,
                "unlabeled": True, "confidence": "low",
            })
            n += 1
        if n:
            print(f"[UNLABELED] {n} unlabeled beam candidates (single-line fallback)")

    return members


def add_unlabeled_lines_universal(members, all_struct_lns, plan_bounds,
                                  page_w, page_h, pts_per_foot,
                                  v_grid=None, h_grid=None,
                                  column_symbols=None):
    """UNIVERSAL unlabeled-beam detection — works at ANY label count.

    Every structural beam line that is NOT already claimed by a labeled beam
    becomes a (beam?) candidate.  Strict false-positive filters ensure only
    genuine structural framing members are flagged — dimension lines, column
    stubs, wall lines, and grid lines are rejected.

    Filters applied (in order):
      F1  Orthogonal only (H / V) — diagonals are braces, not beams.
      F2  Length < 75 % of plan width (H) or height (V) — full-span = grid line.
      F3  Minimum span ≥ 5 ft — stubs / connection plates are shorter.
      F4  Both endpoints must land at a real column position (grid intersection
          or detected column symbol).  This single gate eliminates:
            • dimension lines  (endpoints at annotation ticks, not columns)
            • wall / CMU lines (endpoints at walls, not grid intersections)
            • column stub lines (both ends inside the same column footprint)
          When no grid/symbol data exists the check is skipped (safe fallback).
      F5  Midpoint dedup — one candidate per 40-pt slot.
      F6  Coverage — skip if a labeled beam already occupies this centreline.
      F7  Hard cap 200.
    """
    if not all_struct_lns or not plan_bounds:
        return members
    ppf = pts_per_foot if pts_per_foot > 0 else 9.0
    pb0x, pb0y, pb1x, pb1y = plan_bounds
    plan_w, plan_h = pb1x - pb0x, pb1y - pb0y
    MAX_H_FRAC = 0.70   # multi-bay beams span up to 65% of plan width; sheet borders span >75%
    MAX_V_FRAC = 0.70
    DEDUP_R    = 40.0
    CAP        = 200
    MIN_FT     = 5.0    # F3: beams shorter than 5 ft are stubs / conn. plates

    # ── F4: column-endpoint check ─────────────────────────────────────────────
    # Build augmented column X / Y position lists from grid lines + symbols.
    # Grid lines mark column centrelines; symbols mark individual columns.
    _col_xs = sorted(set(
        [float(x) for x in (v_grid or [])] +
        [s["cx"] for s in (column_symbols or [])]
    ))
    _col_ys = sorted(set(
        [float(y) for y in (h_grid or [])] +
        [s["cy"] for s in (column_symbols or [])]
    ))
    _has_col_data = bool(_col_xs and _col_ys)

    # Tolerance: 36 pt ≈ 4 ft at 1/8" scale.  Generous enough to bridge a
    # drawn-endpoint → column-centre gap without crossing to the next bay
    # (typical minimum steel bay is ~8 ft, so 4 ft is well inside one bay).
    COL_TOL = max(36.0, ppf * 0.5)

    def _dist_to_segment(px, py, sx1, sy1, sx2, sy2):
        """Perpendicular distance from (px, py) to the segment (sx1,sy1)-(sx2,sy2),
        clamped to the segment's own extent (not its infinite-line extension)."""
        sdx, sdy = sx2 - sx1, sy2 - sy1
        seg_len_sq = sdx * sdx + sdy * sdy
        if seg_len_sq < 1e-6:
            return math.hypot(px - sx1, py - sy1)
        t = max(0.0, min(1.0, ((px - sx1) * sdx + (py - sy1) * sdy) / seg_len_sq))
        return math.hypot(px - (sx1 + t * sdx), py - (sy1 + t * sdy))

    def _at_col(ex, ey, is_h):
        """True if (ex, ey) is at a column position (grid intersection or symbol)."""
        if not _has_col_data:
            return True   # no grid data → skip check (safe: no false rejections)
        # A LABELED beam endpoint is direct proof of a real support at that point.
        # Accept it — this recovers candidates that frame into a column the symbol
        # detector missed but a labeled beam confirms (the cause of unlabeled beams
        # dropping when fewer column symbols are detected).
        if any(math.hypot(ex - lex, ey - ley) < COL_TOL for lex, ley in _lab_ends):
            return True
        # A joist/secondary beam commonly bears MID-SPAN on a labeled girder --
        # several joists frame into the same girder at different points along
        # its length, not just at the girder's own two endpoints.  Treat lying
        # on a labeled beam's drawn centreline (anywhere along its span, not
        # just its ends) as an equally real support.  This is a general rule
        # (any drawing with joists framing into girders), not specific to any
        # one sheet.
        if any(_dist_to_segment(ex, ey, lx1, ly1, lx2, ly2) < UNLABELED_PERP_TOL
               for (lx1, ly1, lx2, ly2) in lab):
            return True
        # Longitudinal tolerance remains wide (COL_TOL) to bridge end gaps.
        # Perpendicular tolerance balances two failures: too WIDE re-admits
        # parallel offset lines (dimension strings, canopy boundaries) as false
        # beams; too TIGHT (10 pt) rejects real beams whose endpoint sits a little
        # off the grid row → the cause of unlabeled dropping 83→66.  Tune the
        # module-level UNLABELED_PERP_TOL to trade recall vs false positives.
        x_tol = COL_TOL if is_h else UNLABELED_PERP_TOL
        y_tol = UNLABELED_PERP_TOL if is_h else COL_TOL
        return (min(abs(ex - x) for x in _col_xs) < x_tol and
                min(abs(ey - y) for y in _col_ys) < y_tol)

    # ── Coverage check against already-extracted labeled beams ────────────────
    # Exclude any prior unlabeled candidates so coverage is measured only
    # against real labels — prevents cascading self-suppression.
    lab = [(m["bx1"] * page_w, m["by1"] * page_h,
            m["bx2"] * page_w, m["by2"] * page_h)
           for m in members
           if m.get("type") == "beam" and m.get("bx1") is not None
           and not m.get("unlabeled")]
    # Labeled beam endpoints — real, confirmed support positions used by _at_col
    # above to bridge columns the symbol detector missed.
    _lab_ends = [(a, b) for (a, b, c, d) in lab] + [(c, d) for (a, b, c, d) in lab]

    # Active framing bounding box: lines extending outside the beam framing envelope
    # (e.g. vertical grid line extensions shooting down into margins) are rejected.
    _lab_xs = [a for (a, b, c, d) in lab] + [c for (a, b, c, d) in lab]
    _lab_ys = [b for (a, b, c, d) in lab] + [d for (a, b, c, d) in lab]
    _framing_min_x = min(_lab_xs) - 15.0 if _lab_xs else 0.0
    _framing_max_x = max(_lab_xs) + 15.0 if _lab_xs else page_w
    _framing_min_y = min(_lab_ys) - 15.0 if _lab_ys else 0.0
    _framing_max_y = max(_lab_ys) + 15.0 if _lab_ys else page_h

    seen_lines = []
    def _covered(lx1, ly1, lx2, ly2):
        """True if this line coincides with an already extracted beam."""
        L = math.hypot(lx2 - lx1, ly2 - ly1) or 1.0
        ux, uy = (lx2 - lx1) / L, (ly2 - ly1) / L
        for (ax1, ay1, ax2, ay2) in lab + seen_lines:
            aL = math.hypot(ax2 - ax1, ay2 - ay1) or 1.0
            if abs(((ax2 - ax1) * ux + (ay2 - ay1) * uy) / aL) < 0.96:
                continue                      # not parallel
            if abs((ax1 - lx1) * (-uy) + (ay1 - ly1) * ux) > 18:
                continue                      # too far perpendicular
            t1 = (ax1 - lx1) * ux + (ay1 - ly1) * uy
            t2 = (ax2 - lx1) * ux + (ay2 - ly1) * uy
            overlap = min(L, max(t1, t2)) - max(0.0, min(t1, t2))
            # Covered if overlap is > 40% of the NEW line, OR if it overlaps
            # by more than 10 feet. Because we process short lines first, a long
            # multi-bay grid line will overlap an existing bay-beam by > 10 feet
            # and be correctly rejected instead of duplicating and overshooting.
            if overlap > 0.4 * L or overlap > 10.0 * ppf:
                return True
        return False

    seen, n = [], 0
    rejected_col, rejected_len, rejected_dir = 0, 0, 0
    
    # Sort by length ASCENDING so individual bay-length beams are processed before
    # long, multi-bay grid lines or dimension strings.
    sorted_lns = sorted(all_struct_lns, key=lambda s: s[4])
    # Chain gap: how far apart two drawn fragments can be and still be treated
    # as one broken centreline (bridges gaps created by text callouts like (+14'-10 5/8")).
    _unlab_chain_gap = max(45.0, ppf * 5.0)
    for (lx1, ly1, lx2, ly2, ln) in sorted_lns:
        if n >= CAP:
            break

        # Collinear chaining — a real beam/joist is frequently drawn as several
        # short SOLID segments broken at every crossing girder or bearing seat.
        # Without this, each raw fragment became its own separate (beam?)
        # candidate: a short stub that visually looked "cut midway" instead of
        # running the full length of the actual member. Recover the true
        # extent from the other drawn segments before applying the filters
        # below — this mirrors the stitching already used for labeled beams
        # in detect_beam_lines, applied here only to unlabeled candidates.
        _orig_x1, _orig_y1, _orig_x2, _orig_y2 = lx1, ly1, lx2, ly2
        lx1, ly1, lx2, ly2, ln = _extend_with_thin_segs(
            lx1, ly1, lx2, ly2, all_struct_lns, gap_tol=_unlab_chain_gap)

        # Cap the chain at the nearest REAL crossing girder — not at just any
        # grid reference line. A joist can legitimately run through a grid
        # row that has no actual beam drawn on it in this bay (e.g. straight
        # from row D to row F with nothing physically crossing at row E), so
        # capping on grid-line existence alone chopped those joists short —
        # "cut midway" again, just from the opposite direction. What must be
        # capped is chaining into a DIFFERENT, unrelated member that only
        # coincidentally sits on the same infinite line several rows away
        # (e.g. a joist here and a column line elsewhere). The correct,
        # general test for that is: does a real labeled beam actually cross
        # this fragment's axis between the original extent and the chained
        # end? If yes, stop there (that is the true next support). If no
        # labeled beam crosses, the extension is following one real member,
        # so leave it alone.
        _adx0, _ady0 = abs(_orig_x2 - _orig_x1), abs(_orig_y2 - _orig_y1)
        if _ady0 > _adx0:      # vertical fragment -> look for crossing H beams
            _lo, _hi = min(_orig_y1, _orig_y2), max(_orig_y1, _orig_y2)
            _cx = (_orig_x1 + _orig_x2) / 2
            _above, _below = [], []
            for (ax1, ay1, ax2, ay2) in lab:
                if abs(ay2 - ay1) > abs(ax2 - ax1):
                    continue                      # not a horizontal beam
                axlo, axhi = min(ax1, ax2), max(ax1, ax2)
                if not (axlo - 5 <= _cx <= axhi + 5):
                    continue                      # doesn't span this fragment's x
                ay = (ay1 + ay2) / 2
                if ay < _lo - 2:
                    _above.append(ay)
                elif ay > _hi + 2:
                    _below.append(ay)
            if _above:
                _cap = max(_above)
                if ly1 < _cap: ly1 = _cap
                if ly2 < _cap: ly2 = _cap
            if _below:
                _cap = min(_below)
                if ly1 > _cap: ly1 = _cap
                if ly2 > _cap: ly2 = _cap
            ln = math.hypot(lx2 - lx1, ly2 - ly1)
        elif _adx0 > _ady0:    # horizontal fragment -> look for crossing V beams
            _lo, _hi = min(_orig_x1, _orig_x2), max(_orig_x1, _orig_x2)
            _cy = (_orig_y1 + _orig_y2) / 2
            _left, _right = [], []
            for (ax1, ay1, ax2, ay2) in lab:
                if abs(ax2 - ax1) > abs(ay2 - ay1):
                    continue                      # not a vertical beam
                aylo, ayhi = min(ay1, ay2), max(ay1, ay2)
                if not (aylo - 5 <= _cy <= ayhi + 5):
                    continue                      # doesn't span this fragment's y
                ax = (ax1 + ax2) / 2
                if ax < _lo - 2:
                    _left.append(ax)
                elif ax > _hi + 2:
                    _right.append(ax)
            if _left:
                _cap = max(_left)
                if lx1 < _cap: lx1 = _cap
                if lx2 < _cap: lx2 = _cap
            if _right:
                _cap = min(_right)
                if lx1 > _cap: lx1 = _cap
                if lx2 > _cap: lx2 = _cap
            ln = math.hypot(lx2 - lx1, ly2 - ly1)

        adx, ady = abs(lx2 - lx1), abs(ly2 - ly1)

        # F1: orthogonal only + F2: reject near-full-plan-width/height lines
        if adx > ady * 2:
            bdir = "H"
            is_h = True
            if adx > plan_w * MAX_H_FRAC:
                rejected_dir += 1
                continue
        elif ady > adx * 2:
            bdir = "V"
            is_h = False
            if ady > plan_h * MAX_V_FRAC:
                rejected_dir += 1
                continue
        else:
            rejected_dir += 1
            continue                          # diagonal → skip

        # Reject grid extension lines and margin lines extending outside the active structural framing boundary
        if _lab_xs and _lab_ys:
            mid_x = (lx1 + lx2) / 2.0
            mid_y = (ly1 + ly2) / 2.0
            if mid_x < _framing_min_x - 5.0 or mid_x > _framing_max_x + 5.0 or mid_y < _framing_min_y - 5.0 or mid_y > _framing_max_y + 5.0:
                continue
            if is_h:
                if lx1 < _framing_min_x - 10.0 or lx2 > _framing_max_x + 10.0 or ly1 < _framing_min_y - 10.0 or ly1 > _framing_max_y + 10.0:
                    continue
            else:
                if ly1 < _framing_min_y - 10.0 or ly2 > _framing_max_y + 10.0 or lx1 < _framing_min_x - 10.0 or lx1 > _framing_max_x + 10.0:
                    continue
                if min(ly1, ly2) >= _framing_max_y - 15.0 or max(ly1, ly2) <= _framing_min_y + 15.0:
                    continue

        # F3: minimum structural length
        if ln / ppf < MIN_FT:
            rejected_len += 1
            continue

        # F4: BOTH endpoints must be at a real column position.
        # This is the primary false-positive gate — dimension lines, wall lines,
        # and grid lines do NOT span column-to-column in both axes.
        if not (_at_col(lx1, ly1, is_h) and _at_col(lx2, ly2, is_h)):
            rejected_col += 1
            continue

        # ── Column-centreline snap ────────────────────────────────────────────
        # Beams are drawn column-FACE to column-FACE in CAD (the clear span),
        # but we display column-CENTRE to column-CENTRE (the overall span).
        # Snap each endpoint to the nearest column grid position — identical to
        # Pass 3d in detect_beam_lines — so unlabelled lines reach exactly
        # column-to-column, matching labelled beam behaviour.
        # Only snap when the two ends target DIFFERENT column positions so we
        # never collapse both endpoints onto the same column.
        if _has_col_data:
            if bdir == "H" and _col_xs:
                _gx1 = min(_col_xs, key=lambda gx: abs(lx1 - gx))
                _gx2 = min(_col_xs, key=lambda gx: abs(lx2 - gx))
                if abs(_gx1 - _gx2) > 5:
                    if abs(lx1 - _gx1) <= COL_TOL:
                        lx1 = _gx1
                    if abs(lx2 - _gx2) <= COL_TOL:
                        lx2 = _gx2
            elif bdir == "V" and _col_ys:
                _gy1 = min(_col_ys, key=lambda gy: abs(ly1 - gy))
                _gy2 = min(_col_ys, key=lambda gy: abs(ly2 - gy))
                if abs(_gy1 - _gy2) > 5:
                    if abs(ly1 - _gy1) <= COL_TOL:
                        ly1 = _gy1
                    if abs(ly2 - _gy2) <= COL_TOL:
                        ly2 = _gy2

        # Recompute midpoint + length after snap
        mx, my = (lx1 + lx2) / 2, (ly1 + ly2) / 2
        ln = math.hypot(lx2 - lx1, ly2 - ly1)

        # F3b: re-validate minimum length AFTER the column-centreline snap.
        # The snap above moves each endpoint independently toward its OWN
        # nearest column/grid position -- usually this only stretches a
        # face-to-face span out to centre-to-centre, but when both raw
        # endpoints already sit near columns that are close together, the
        # snap can pull them toward each other instead and collapse a
        # candidate that only just cleared F3 down to a 3-4 ft stub. That is
        # exactly what turned bearing-seat tick marks, detail-bubble leaders,
        # and connection-symbol glyphs into spurious floating "(beam?)"
        # fragments (visible as short disconnected segments in the 3D view,
        # unrelated to any real beam/joist). Re-checking here — universally,
        # on any drawing — closes that gap.
        if ln / ppf < MIN_FT:
            rejected_len += 1
            continue

        # F5: midpoint dedup
        if any(math.hypot(mx - sx, my - sy) < DEDUP_R for sx, sy in seen):
            continue

        # F6: coverage — skip lines already claimed by a labeled beam
        if _covered(lx1, ly1, lx2, ly2):
            continue

        seen.append((mx, my))
        seen_lines.append((lx1, ly1, lx2, ly2))
        Lft = ln / ppf
        members.append({
            "profile": "(beam?)", "type": "beam",
            "length_ft": round(Lft, 1),
            "beam_dir": bdir,
            "bx1": round(lx1 / page_w, 4), "by1": round(ly1 / page_h, 4),
            "bx2": round(lx2 / page_w, 4), "by2": round(ly2 / page_h, 4),
            "x":  round(mx / page_w, 4),   "y":  round(my / page_h, 4),
            "lx": round(mx / page_w, 4),   "ly": round(my / page_h, 4),
            "sx": None, "sy": None, "w": 0.025, "h": 0.012,
            "color": "#F59E0B",
            "confirmed": False, "is_column": False,
            "unlabeled": True, "confidence": "low",
        })
        n += 1

    print(f"[UNLABELED] {n} universal (beam?) candidates "
          f"(rejected: dir/len={rejected_dir+rejected_len} col_gate={rejected_col})")
    return members


# Diagnostic-only capture of every column-symbol candidate's structural-
# validation outcome from the MOST RECENT emit_symbol_columns() call --
# reset and repopulated at the top of every call. Not used by any real code
# path; exists so a "why did the foundation plan only extract some of its
# columns" question can be answered with real per-candidate scores instead
# of guessing, by re-running extraction (which calls emit_symbol_columns
# normally, no side effects added) and then reading this back via
# GET /pages/{id}/debug/column-validation-log. See model.py for that route.
_LAST_COLUMN_VALIDATION_LOG: list = []


def emit_symbol_columns(members, column_symbols, v_grid, h_grid,
                        page_w, page_h, scale_ratio: float = 96,
                        pts_per_foot: float = 0.0, profiles=None,
                        is_foundation_plan: bool = False):
    """Emit a COLUMN member for each detected column symbol that sits at a grid
    intersection and isn't already represented by a column member.

    On framing plans the columns are I/H symbols at grid crossings with no size
    label of their own (they're sized on the Column Schedule), so they were
    never counted.  Here we count them: position = symbol, size left blank (a
    later Column-Schedule pass can fill it).  Gating on a grid intersection
    (near a vertical AND a horizontal grid line) keeps false marks out.

    is_foundation_plan: the MIN_BEAMS gate below ("only count a symbol as a
    column if at least 2 beams visibly frame into it") was written for
    framing plans, where a real column always has beams landing on it and a
    stray annotation mark never does. A foundation/column plan has NO beams
    at all -- footings and piers are the whole point of the sheet -- so that
    gate silently rejected every single column symbol on a foundation plan,
    which is exactly the "Column: 0" bug reported on a sheet that's visibly
    covered in footing/column marks. On a foundation plan, grid-intersection
    proximity (or, failing that, just being a real detected symbol at all)
    is itself sufficient evidence -- there's no beam signal to require.
    """
    if not column_symbols:
        column_symbols = []

    global _LAST_COLUMN_VALIDATION_LOG
    _LAST_COLUMN_VALIDATION_LOG = []

    # ── Scale-aware thresholds ────────────────────────────────────────────────
    _ipt = 72.0 / max(scale_ratio, 1)
    if pts_per_foot <= 0.0:
        pts_per_foot = 72.0 / max(scale_ratio, 1) * 12.0

    FRAME_IN  = 24.0
    FRAME_PT  = FRAME_IN * _ipt
    END_EQ_IN = 4.0
    END_EQ_PT = END_EQ_IN * _ipt
    MIN_BEAMS = 2
    SNAP_IN = 6.0
    SNAP_PT = SNAP_IN * _ipt
    # 2026-07-27: was 6.0in (~3.4pt at a typical 3/32"=1'-0" scale) -- far
    # smaller than the physical footprint of a real column/footing symbol
    # (typically 1-3 REAL FEET across). The raw shape detector frequently
    # produces more than one sub-shape for a single physical symbol (e.g.
    # the outer dashed footing outline and the inner "H"/pier tick get
    # picked up as two separate candidates), and their centroids can easily
    # sit 1-2 ft apart -- well outside a 6in dedup radius but nowhere near
    # the 15ft+ spacing of genuinely distinct real columns. Raised to 24in
    # (2ft): big enough to catch same-symbol duplicate detections, still an
    # order of magnitude below any real column-to-column spacing, so two
    # legitimately separate close columns are never merged.
    DEDUP_IN = 24.0
    DEDUP_PT = DEDUP_IN * _ipt

    existing_with_raw = [
        (m["x"] * page_w, m["y"] * page_h,
         ((m.get("geometry") or {}).get("raw_x") or m["x"]) * page_w,
         ((m.get("geometry") or {}).get("raw_y") or m["y"]) * page_h)
        for m in members if m.get("type") == "column" and m.get("x") is not None and m.get("y") is not None
    ]
    added: list[tuple[float, float, float, float]] = []

    # General bay size (avg grid spacing), used by the Column Validation
    # Engine's grid-intersection scoring below -- distinct from the
    # foundation-plan-only _grid_envelope block further down, which uses a
    # bay size just to add slack around the envelope. This one just needs
    # "how far off grid is close, relatively, on THIS sheet" so a candidate
    # a few points off grid on a tightly-spaced sheet isn't scored the same
    # as one the same distance off grid on a widely-spaced sheet.
    _bay_size_pt = None
    if v_grid and len(v_grid) > 1:
        _bay_size_pt = (max(v_grid) - min(v_grid)) / (len(v_grid) - 1)
    elif h_grid and len(h_grid) > 1:
        _bay_size_pt = (max(h_grid) - min(h_grid)) / (len(h_grid) - 1)

    # Foundation plans only: reject any symbol far outside the actual
    # structural grid envelope entirely (not just "off_grid", which still
    # kept it). Real footing/column marks sit within the building's grid
    # system; a symbol out in the open margin/notes area (duct-bank callouts,
    # retaining-wall references, general notes) or riding on an unrelated
    # symbol (e.g. a triangular brace-frame mark) can still coincidentally
    # pass the shape/dash checks in detect_column_symbols, and those were
    # showing up as columns scattered outside the building footprint. One
    # bay-width of slack beyond the outermost real grid lines still allows a
    # genuinely eccentric footing near the building edge.
    # Reverted (2026-07-20): a same-axis-alignment self-correcting extension
    # was tried here and immediately disproven live -- on the "sasa"
    # foundation plan it pulled in an entire row/column of REAL PDF content
    # that isn't a footing or column at all ("SEE ARCH / C-L BEAM" centerline
    # dimension callouts, "ELEVATOR SILL" note text), because dimension/note
    # annotations near a sheet's top and side edges are themselves often
    # evenly spaced and lined up with the grid -- alignment alone is NOT
    # sufficient evidence of a real missing grid line, it was the wrong
    # signal. Back to the simple, safe one-bay-width margin below. The real
    # fix for "foundation plan doesn't extract every real column" has to be
    # at grid-line detection itself (why extract_grid_lines() missed a real
    # bubble label) or at the symbol classifier (why a dimension centerline
    # mark and a footing mark aren't distinguished) -- not here.
    _grid_envelope = None
    if is_foundation_plan and v_grid and h_grid:
        _bay_x = (max(v_grid) - min(v_grid)) / max(len(v_grid) - 1, 1) if len(v_grid) > 1 else 60.0
        _bay_y = (max(h_grid) - min(h_grid)) / max(len(h_grid) - 1, 1) if len(h_grid) > 1 else 60.0
        _grid_envelope = (
            min(v_grid) - _bay_x, min(h_grid) - _bay_y,
            max(v_grid) + _bay_x, max(h_grid) + _bay_y,
        )

    # Best-guess profile for a symbol-only column with no label of its own --
    # matches SteelGenie's own behavior (verified live: an unlabeled column
    # symbol still gets a real guessed section, e.g. "W12X79", flagged with a
    # warning + "Need Review" status, rather than a placeholder like "COL").
    # Guess = whichever real column-type profile already appears most often
    # elsewhere in this project's labeled members -- a far better guess than
    # a fixed constant, since it reflects what this specific project actually
    # uses. Falls back to a common light structural column size only when
    # nothing else on the page gives any hint at all.
    _COL_PROFILE_RE = re.compile(r'^(?:W\d{1,2}X\d{1,3}|HSS\d+(?:\.\d+)?X\d+(?:\.\d+)?X[\d./]+|PIPE\S*)$', re.IGNORECASE)
    _col_profile_counts: dict[str, int] = {}
    for m in members:
        if m.get("type") == "column":
            prof = (m.get("profile") or "").upper().strip()
            if prof and _COL_PROFILE_RE.match(prof):
                _col_profile_counts[prof] = _col_profile_counts.get(prof, 0) + 1
    _guessed_profile = (max(_col_profile_counts, key=_col_profile_counts.get)
                         if _col_profile_counts else None)

    beam_ends = []
    beam_end_dirs: dict[tuple[float, float], str] = {}
    for m in members:
        if m.get("type") == "beam" and m.get("bx1") is not None:
            e1 = (m["bx1"] * page_w, m["by1"] * page_h)
            e2 = (m["bx2"] * page_w, m["by2"] * page_h)
            beam_ends.append(e1)
            beam_ends.append(e2)
            bdir = m.get("beam_dir")
            if bdir:
                beam_end_dirs[e1] = bdir
                beam_end_dirs[e2] = bdir

    added: list[tuple[float, float]] = []
    rejected = 0

    for s in column_symbols:
        cx, cy = s["cx"], s["cy"]   # union-bbox centre (raw)

        # 2026-07-20: the envelope gate used to be an unconditional hard
        # reject for ANY candidate outside it. That's exactly what caused
        # the original "foundation plan doesn't extract every real column"
        # bug -- the envelope is only as good as extract_grid_lines()'s own
        # grid-bubble detection, and a real footing sitting just past an
        # UNDETECTED outermost grid line got thrown out here even though it
        # has genuine footing-shape evidence and a real "F1"/"P2"-style mark
        # next to it. Bare geometric alignment with the grid is NOT
        # structural evidence (that's the exact reasoning that produced the
        # false-positive "℄ BEAM" / "ELEVATOR SILL" incident and was
        # reverted) -- but a real mark match IS: it's independent textual
        # confirmation this is a labeled structural member, not a guess from
        # position alone. So the envelope stays a hard gate for anything
        # WITHOUT that kind of confirmed evidence (classifier_confidence
        # below the "real mark nearby" threshold -- see
        # column_symbol_classifier.py's has_mark-gated rules, which top out
        # at 0.45 with no mark and jump to >=0.65 once a real F/P/C mark is
        # found), and only lets a candidate through past it when the
        # classifier has already confirmed real structural evidence, not
        # merely a plausible shape in a plausible place.
        _classifier_conf = s.get("classifier_confidence") or 0.0
        # 2026-07-20: threshold sits strictly ABOVE the classifier's own
        # highest no-mark/shape-only confidence (ih_pattern with no tight-
        # radius mark match tops out at 0.65 -- see
        # column_symbol_classifier.py) and AT/BELOW its lowest real-mark-
        # confirmed confidence (a footing outline + tight-radius F/P/C mark
        # is 0.70). This is the actual dividing line between "shape looked
        # plausible" and "an independent structural label confirms it" --
        # live-verified: at 0.65 this let three real annotation clusters
        # (a dimension-centerline callout, a leader-note callout, a rebar
        # detail heading) bypass the envelope on shape-pattern confidence
        # alone with no real mark; raising to 0.70 excludes all of them
        # while still letting confirmed-mark footings/columns through.
        _has_confirmed_evidence = _classifier_conf >= 0.70
        if _grid_envelope is not None and not _has_confirmed_evidence:
            _ex0, _ey0, _ex1, _ey1 = _grid_envelope
            if not (_ex0 <= cx <= _ex1 and _ey0 <= cy <= _ey1):
                rejected += 1
                _LAST_COLUMN_VALIDATION_LOG.append({
                    "cx": cx, "cy": cy, "category": s.get("category"),
                    "outcome": "rejected", "stage": "grid_envelope",
                    "classifier_confidence": _classifier_conf,
                    "reason": "outside grid envelope and no confirmed mark/shape evidence "
                              f"(classifier_confidence={_classifier_conf:.2f} < 0.65)",
                })
                continue
        elif _grid_envelope is not None:
            _ex0, _ey0, _ex1, _ey1 = _grid_envelope
            if not (_ex0 <= cx <= _ex1 and _ey0 <= cy <= _ey1):
                # Outside the envelope but has confirmed evidence (real mark
                # match) -- let it through, but record why for the debug log.
                _LAST_COLUMN_VALIDATION_LOG.append({
                    "cx": cx, "cy": cy, "category": s.get("category"),
                    "outcome": "envelope_bypassed", "stage": "grid_envelope",
                    "classifier_confidence": _classifier_conf,
                    "reason": "outside grid envelope but confirmed by classifier "
                              f"(confidence={_classifier_conf:.2f}, category={s.get('category')}) "
                              "-- likely a real footing/column past an undetected grid line",
                })

        # Count distinct beam endpoints framing into this symbol.
        close_ends = [(ex, ey) for ex, ey in beam_ends
                      if math.hypot(cx - ex, cy - ey) < FRAME_PT]
        unique_ends = []
        for (ex, ey) in close_ends:
            if not any(math.hypot(ex - ux, ey - uy) < END_EQ_PT
                       for ux, uy in unique_ends):
                unique_ends.append((ex, ey))

        # Only require framing beam support for unconfirmed, un-classified shapes.
        # A real drawn I/H column symbol (e.g. on a pile cap/corner), a filled rect,
        # or an approved column category with a reference mark (P1, CC1, etc.) IS a column
        # and must NEVER be discarded just because beams are absent on this sheet/detail.
        is_confirmed_symbol = (
            s.get("has_ih_pattern") or
            "ih_pattern" in s.get("accept_rules", []) or
            "filled_rect" in s.get("accept_rules", []) or
            s.get("category") in ("steel_column", "concrete_column", "footing_isolated", "pile_cap", "pedestal", "hss_column") or
            _classifier_conf >= 0.60 or
            is_foundation_plan
        )
        if len(unique_ends) < MIN_BEAMS and not is_confirmed_symbol:
            rejected += 1
            _LAST_COLUMN_VALIDATION_LOG.append({
                "cx": cx, "cy": cy, "category": s.get("category"),
                "outcome": "rejected", "stage": "min_beams",
                "beam_end_count": len(unique_ends),
            })
            continue

        # Use the inner column symbol centre (smallest rect in cluster)
        # as the raw detected position — this is where the actual column
        # square / base-plate lives on the drawing, not the outer footing.
        # Falls back to cx/cy (union centroid) for framing-plan columns
        # that have no surrounding footing outline in their cluster.
        raw_x = s.get("inner_cx", cx)
        raw_y = s.get("inner_cy", cy)

        # Requirement §5: validate marker centre lies inside the detected
        # cluster bbox.  If inner_cx/inner_cy somehow falls outside the
        # whole union bbox (e.g. degenerate single-point cluster), fall back
        # to the union bbox centre so the marker is at worst on the cluster,
        # never in a completely wrong position.
        _sbbox = s.get("bbox")
        if _sbbox is not None:
            _bx0, _by0, _bx1, _by1 = _sbbox
            if not (_bx0 <= raw_x <= _bx1 and _by0 <= raw_y <= _by1):
                # inner centre escaped the bbox — use bbox midpoint instead
                raw_x = (_bx0 + _bx1) / 2
                raw_y = (_by0 + _by1) / 2
                print(f"[COL] inner_cx/cy ({s.get('inner_cx'):.0f},{s.get('inner_cy'):.0f}) "
                      f"outside cluster bbox {_sbbox}, falling back to bbox centre")

        off_grid = True
        snap_x, snap_y = raw_x, raw_y

        gx, gy = None, None
        if v_grid:
            gx = min(v_grid, key=lambda g: abs(cx - g))
            if abs(cx - gx) <= SNAP_PT:
                snap_x = gx
                off_grid = False
        if h_grid:
            gy = min(h_grid, key=lambda g: abs(cy - g))
            if abs(cy - gy) <= SNAP_PT:
                snap_y = gy
                off_grid = False

        px, py = snap_x, snap_y

        if any(math.hypot(px - ex, py - ey) < DEDUP_PT or math.hypot(raw_x - rx, raw_y - ry) < DEDUP_PT
               for ex, ey, rx, ry in existing_with_raw + added):
            continue

        # Match labels (within 20pt)
        has_label_match = False
        matched_profile = _guessed_profile
        if profiles:
            for p in profiles:
                if math.hypot(cx - p["cx"], cy - p["cy"]) < 20.0:
                    has_label_match = True
                    matched_profile = p["profile"]
                    break

        # Column Validation Engine: don't trust geometry/label matching
        # alone. Combine grid-intersection proximity, the Symbol
        # Classification Engine's own footing/column category+confidence,
        # how close the nearest real mark actually is (not just "one was
        # somewhere in range"), and beam connectivity into one structural-
        # context score. A candidate that clears every geometric filter
        # upstream (shape match, classifier, mark-radius) can still fail
        # here if ALL of those signals are simultaneously weak -- that
        # combination is what a circular annotation bubble or a stray
        # detail marker that dodged the earlier curve-based checks looks
        # like structurally, even when its shape looked plausible.
        grid_snap_dist = None
        if gx is not None and gy is not None:
            grid_snap_dist = math.hypot(cx - gx, cy - gy)
        elif gx is not None:
            grid_snap_dist = abs(cx - gx)
        elif gy is not None:
            grid_snap_dist = abs(cy - gy)

        ctx_score, ctx_signals, ctx_passed = column_validation_engine.score_column_candidate(
            has_grid_intersection=not off_grid,
            grid_snap_dist_pt=grid_snap_dist,
            bay_size_pt=_bay_size_pt,
            classifier_category=s.get("category"),
            classifier_confidence=s.get("classifier_confidence"),
            nearest_mark_dist_pt=s.get("nearest_mark_dist"),
            mark_radius_pt=s.get("mark_radius"),
            beam_end_count=len(unique_ends),
            is_foundation_plan=is_foundation_plan,
            schedule_matched=False,  # not known at page-extraction time; see registration.py
        )
        # A real label match on the symbol itself (framing-plan profile
        # callout, e.g. "W12X40" sitting right on the mark) is independent,
        # strong positive evidence the structural-context score above has
        # no way to see -- fold it in as a flat bonus rather than losing it.
        if has_label_match:
            ctx_score = round(min(1.0, ctx_score + 0.25), 3)

        # Grid index naming -- computed here, before _reason_parts(), because
        # that closure reads grid_ref as a free variable: if grid_ref were
        # only assigned later in this same loop body (as it used to be, right
        # after this block was originally written), Python raises "cannot
        # access free variable 'grid_ref' where it is not associated with a
        # value in enclosing scope" on the closure's first read each
        # iteration -- this crashed extraction on every page that reached
        # this code path (re-diagnosed and re-fixed 2026-07-21 after being
        # reverted along with an unrelated feature; see the reason string
        # below is the ONLY thing that needs grid_ref before this point).
        v_idx = sorted(v_grid).index(gx) + 1 if v_grid and gx is not None and gx in v_grid else "?"
        h_idx = sorted(h_grid).index(gy) + 1 if h_grid and gy is not None and gy in h_grid else "?"
        grid_ref = f"{v_idx}-{h_idx}" if (v_idx != "?" or h_idx != "?") else None

        # Human-readable reason string (mandate's "confidence model" format:
        # every accepted/rejected candidate states WHY). Built from the
        # strongest signals actually present rather than a generic dump of
        # ctx_signals, so the debug log/overlay reads like an engineer's
        # note, not a data structure.
        def _reason_parts():
            parts = []
            _cat = s.get("category")
            if _cat:
                parts.append(f"category={_cat}")
            if s.get("classifier_reason"):
                parts.append(s["classifier_reason"])
            if not off_grid:
                parts.append(f"on grid {grid_ref}" if grid_ref else "on grid intersection")
            else:
                parts.append("off grid")
            if has_label_match:
                parts.append(f"matched profile label '{matched_profile}'")
            if len(unique_ends) >= 2:
                parts.append(f"{len(unique_ends)} beam ends frame in")
            parts.append(f"confidence {ctx_score:.2f}")
            return "; ".join(parts)

        _is_col_cat = s.get("category") in (
            "steel_column", "hss_column", "pipe_column", "built_up_column",
            "concrete_column", "footing_isolated", "pedestal"
        )
        if not ctx_passed and not has_label_match and not _is_col_cat and off_grid:
            rejected += 1
            _LAST_COLUMN_VALIDATION_LOG.append({
                "cx": cx, "cy": cy, "category": s.get("category"),
                "outcome": "rejected", "stage": "validation_engine",
                "ctx_score": ctx_score, "ctx_signals": ctx_signals,
                "has_label_match": has_label_match,
                "beam_end_count": len(unique_ends), "off_grid": off_grid,
                "classifier_confidence": s.get("classifier_confidence"),
                "reason": "Rejected: " + _reason_parts(),
            })
            continue

        _LAST_COLUMN_VALIDATION_LOG.append({
            "cx": cx, "cy": cy, "category": s.get("category"),
            "outcome": "accepted", "stage": "validation_engine",
            "ctx_score": ctx_score, "ctx_signals": ctx_signals,
            "has_label_match": has_label_match,
            "beam_end_count": len(unique_ends), "off_grid": off_grid,
            "classifier_confidence": s.get("classifier_confidence"),
            "reason": "Accepted: " + _reason_parts(),
        })

        score = ctx_score
        status = 'active' if score >= column_validation_engine.REVIEW_FLOOR else 'need_review'

        # error_flags drives the 2D overlay's red "needs attention" styling
        # (ColumnSymbol.tsx: any flag other than "suggested" -> red). "no_label"
        # and "orphan" were written for FRAMING-plan columns, where a real
        # column normally has both a size label AND beams framing into it, so
        # missing either is a genuine anomaly worth flagging red. On a
        # foundation plan neither is true by design -- profile lives on a
        # separate Column Schedule sheet (never a label here) and there are
        # no beams on this sheet type at all -- so every single legitimate
        # footing column tripped both flags unconditionally, turning the
        # entire sheet red instead of highlighting real problems. SteelGenie
        # doesn't do this either: verified live, their guessed/no-label
        # columns render with the same plain symbol as any other column: the
        # "guessed" signal only shows up in the properties panel (status +
        # warning icon), not as a loud 2D overlay color.
        error_flags = []
        if off_grid:
            error_flags.append("no_grid")
        if not is_foundation_plan:
            if not has_label_match:
                error_flags.append("no_label")
            if len(unique_ends) < 2:
                error_flags.append("orphan")

        # v_idx/h_idx/grid_ref already computed above, before _reason_parts().

        added.append((px, py, raw_x, raw_y))

        # Stage 3 (2026-07-17 rebuild, live-verified against the real
        # SteelGenie app): on a real foundation plan, the footing outline
        # ("F80 (-1.50')") and the column that lands on it (short diagonal
        # I-icon + profile, "W12X53") are TWO linked records, not one. This
        # codebase's shape detection still clusters the outline and the
        # inner tick-mark sub-paths into a single geometric symbol before
        # classification ever runs (see column_symbol_classifier.py's rule
        # 6b docstring for why that's still correct for DETECTION) -- this
        # is the point where that merged detection is split back into two
        # separate members again: a kind="footing" record and a
        # kind="column" record, sharing one linked_group_id so the 3D
        # viewer/BOM can associate them later. Every OTHER category
        # (steel_column, pile_cap, concrete_column, etc.) is unchanged --
        # still emitted as the single column member it always was, so this
        # is additive to foundation-plan footing symbols specifically, not
        # a rewrite of column emission overall.
        _category = s.get("category")

        # Stage 6 Part 2 (2026-07-17, live-verified against real SteelGenie):
        # the shape-acceptance rule(s) that got a candidate through
        # detection are a far more reliable "what icon should this render
        # as" signal than refine_column_geometry's symbol_type, which
        # defaults to "I" for almost any non-circle/non-bare-rect shape --
        # including a plain 4-line footing outline (see the _accept_rules
        # comment above). A footing_isolated match is ALWAYS an outline box
        # in the real drawing, so force "BOX" for it regardless of what
        # symbol_type guessed. Also carry the real detected bounding-box
        # size through (as a page-fraction, same units as x/y) so the 2D
        # overlay can size the box glyph to the ACTUAL mark instead of a
        # generic fixed square -- exactly what the user flagged as missing.
        _real_symbol = "BOX" if _category == "footing_isolated" else s.get("symbol", "I")
        _sym_w_frac = round((s.get("bbox_w") or 0.0) / page_w, 4)
        _sym_h_frac = round((s.get("bbox_h") or 0.0) / page_h, 4)

        if _category == "footing_isolated":
            import uuid as _uuid_mod
            linked_group_id = str(_uuid_mod.uuid4())
            members.append({
                "profile": None, "type": "footing", "length_ft": 0.0,
                "beam_dir": None,
                "bx1": None, "by1": None, "bx2": None, "by2": None,
                "x":  round(px / page_w, 4), "y":  round(py / page_h, 4),
                "lx": round(px / page_w, 4), "ly": round(py / page_h, 4),
                "sx": round(px / page_w, 4), "sy": round(py / page_h, 4),
                "rotation": s.get("rotation", 0),
                "source": "vector_symbol",
                "status": status,
                "geometry": {
                    "x": round(px / page_w, 4),
                    "y": round(py / page_h, 4),
                    "raw_x": round(raw_x / page_w, 4),
                    "raw_y": round(raw_y / page_h, 4),
                    "grid_ref": grid_ref,
                    "symbol": _real_symbol,
                    "sym_w": _sym_w_frac,
                    "sym_h": _sym_h_frac,
                    "category": _category,
                    "linked_group_id": linked_group_id,
                    "linked_role": "footing",
                    "error_flags": error_flags,
                },
                "w": 0.02, "h": 0.02,
                "color": MEMBER_COLORS.get("footing", MEMBER_COLORS["column"]), "confirmed": True,
                "is_column": False, "size_unknown": True,
            })
        else:
            linked_group_id = None

        members.append({
            "profile": matched_profile, "type": "column", "length_ft": 0.0,
            "beam_dir": None,
            "bx1": None, "by1": None, "bx2": None, "by2": None,
            "x":  round(px / page_w, 4), "y":  round(py / page_h, 4),
            "lx": round(px / page_w, 4), "ly": round(py / page_h, 4),
            "sx": round(px / page_w, 4), "sy": round(py / page_h, 4),
            "rotation": s.get("rotation", 0),
            "source": "vector_symbol",
            "status": status,
            "geometry": {
                "x": round(px / page_w, 4),
                "y": round(py / page_h, 4),
                "raw_x": round(raw_x / page_w, 4),
                "raw_y": round(raw_y / page_h, 4),
                "snap_offset_ft": round(math.hypot(px - raw_x, py - raw_y) / pts_per_foot, 2) if pts_per_foot > 0 else 0.0,
                "grid_ref": grid_ref,
                # A column linked to a footing is the small diagonal I/H
                # tick mark next to the footing box in the real drawing, not
                # the outline itself -- detection can't yet tell that tick
                # apart from the outline (same merged cluster, see the
                # comment above), so it keeps the small fixed-size I/H icon
                # rather than inheriting the footing's real (much larger)
                # bounding box. A standalone column (no linked footing) IS
                # its own real detected shape, so it gets the real size.
                "symbol": s.get("symbol", "I") if linked_group_id else _real_symbol,
                "sym_w": None if linked_group_id else _sym_w_frac,
                "sym_h": None if linked_group_id else _sym_h_frac,
                "depth_in": round(s.get("depth_in", 12.0), 1),
                "category": _category,
                "linked_group_id": linked_group_id,
                "linked_role": "column" if linked_group_id else None,
                "error_flags": error_flags,
                # Matches SteelGenie's own "Section size of this member is
                # guessed by the Steel Genie" warning -- true whenever this
                # column had no real profile label of its own and got the
                # best-guess profile (_guessed_profile) instead.
                "guessed": not has_label_match,
            },
            "w": 0.018, "h": 0.018,
            "color": MEMBER_COLORS["column"], "confirmed": True,
            "is_column": True, "size_unknown": not has_label_match,
        })

    # ── Emit Suggested Ghost Columns ──────────────────────────────────────────
    # Framing plans: columns sit at grid intersections where beams/girders frame into or cross
    if v_grid and h_grid and not is_foundation_plan:
        _FRAME_DIST = max(36.0, pts_per_foot * 4.0)
        for gx in v_grid:
            for gy in h_grid:
                close_ends = [(ex, ey) for ex, ey in beam_ends
                              if math.hypot(gx - ex, gy - ey) < _FRAME_DIST]
                # Also check if any beam center passes through this grid intersection
                crossing_beams = []
                for m in members:
                    if m.get("type") == "beam" and m.get("bx1") is not None:
                        bx1, by1 = m["bx1"] * page_w, m["by1"] * page_h
                        bx2, by2 = m["bx2"] * page_w, m["by2"] * page_h
                        if min(bx1, bx2) - 15 <= gx <= max(bx1, bx2) + 15 and min(by1, by2) - 15 <= gy <= max(by1, by2) + 15:
                            dx, dy = bx2 - bx1, by2 - by1
                            if dx*dx + dy*dy > 0:
                                t = max(0, min(1, ((gx - bx1)*dx + (gy - by1)*dy) / (dx*dx + dy*dy)))
                                proj_x, proj_y = bx1 + t*dx, by1 + t*dy
                                if math.hypot(gx - proj_x, gy - proj_y) < 14.0:
                                    crossing_beams.append(m)

                if len(close_ends) >= 1 or len(crossing_beams) >= 1:
                    has_col = False
                    for m in members:
                        if m.get("type") == "column":
                            mx, my = m["x"] * page_w, m["y"] * page_h
                            if math.hypot(gx - mx, gy - my) < DEDUP_PT:
                                has_col = True
                                break
                    if not has_col:
                        v_idx = sorted(v_grid).index(gx) + 1
                        h_idx = sorted(h_grid).index(gy) + 1
                        grid_ref = f"{v_idx}-{h_idx}"

                        members.append({
                            "profile": "COL", "type": "column", "length_ft": 0.0,
                            "beam_dir": None,
                            "bx1": None, "by1": None, "bx2": None, "by2": None,
                            "x":  round(gx / page_w, 4), "y":  round(gy / page_h, 4),
                            "lx": round(gx / page_w, 4), "ly": round(gy / page_h, 4),
                            "sx": round(gx / page_w, 4), "sy": round(gy / page_h, 4),
                            "rotation": 90,
                            "source": "grid_intersection",
                            "status": "active",
                            "confirmed": True,
                            "is_column": True,
                            "w": 0.018, "h": 0.018,
                            "color": MEMBER_COLORS["column"],
                            "geometry": {
                                "x": round(gx / page_w, 4),
                                "y": round(gy / page_h, 4),
                                "raw_x": round(gx / page_w, 4),
                                "raw_y": round(gy / page_h, 4),
                                "snap_offset_ft": 0.0,
                                "grid_ref": grid_ref,
                                "symbol": "I",
                                "depth_in": 12.0,
                                "error_flags": [],
                            }
                        })

    print(f"[COLUMNS] emitted {len(added)} symbol columns "
          f"(rejected {rejected} fp — < {MIN_BEAMS} beam endpoints; "
          f"scale_ratio={scale_ratio}  FRAME={FRAME_IN}\" real  SNAP={SNAP_IN}\" real)")

    # Diagnostic-only: persist the validation log to a file rather than a
    # module-level global. A background-task worker can end up running this
    # function under a DIFFERENT `main` module object than the one a debug
    # endpoint's `import main` resolves to (Python treats the app's own
    # entrypoint module, __main__, as a separate identity from a later
    # `import main` of the same file) -- a plain in-memory global silently
    # diverges between the two, so the debug endpoint would always read back
    # an empty list even though this function ran and populated its own
    # copy. A file on disk has no such identity split.
    try:
        import json as _json
        _log_path = os.path.join(os.path.dirname(__file__), "_column_validation_debug.json")
        with open(_log_path, "w") as _f:
            _json.dump(_LAST_COLUMN_VALIDATION_LOG, _f)
    except Exception as _exc:
        print(f"[COLUMNS] could not write validation debug log: {_exc}")
    return members


def extract_col_text_columns(page, page_w, page_h, members,
                              v_grid=None, h_grid=None, scale_ratio: float = 96):
    """
    Emit columns from 'COL' text labels — placed at the BEAM CONVERGENCE POINT
    nearest to the label, never at the text label origin itself.

    All distance thresholds derived from real-world inches (same conversion as
    emit_symbol_columns) so they stay correct across sheets at different scales.

    Algorithm per label:
      1. Find beam-endpoint cluster within SEARCH_PT of the label centre.
         A cluster = ≥ MIN_BEAMS beam endpoints within CLUSTER_PT of each other.
      2. Place column at the cluster CENTROID — the exact beam convergence point.
      3. Store raw convergence point AND attempt grid snap within GRID_SNAP_PT.
         If grid snap succeeds → use snapped position (off_grid=False).
         If not → keep raw convergence point (off_grid=True).  Do NOT discard.
      4. If no beam cluster: try grid snap near label as fallback.
      5. If neither: discard — never place at bare label position.
    """
    _COL_LABEL_RE = re.compile(r'^\s*COL\.?\s*$', re.I)

    # ── Scale-aware thresholds ────────────────────────────────────────────────
    _ipt = 72.0 / max(scale_ratio, 1)

    # Search radius from COL label to beam endpoint cluster.
    # Labels are typically offset 6-18" from the column; 20" covers generous
    # title-block font placement without reaching unrelated elements.
    SEARCH_PT   = 20.0 * _ipt

    # Radius within which beam endpoints belong to the SAME convergence cluster.
    # 4" real covers all typical beam-end drafting imprecision.
    CLUSTER_PT  = 4.0 * _ipt

    MIN_BEAMS   = 2

    # Grid snap tolerance and dedup — same logic as emit_symbol_columns.
    GRID_SNAP_PT = 6.0 * _ipt
    DEDUP_PT     = 6.0 * _ipt

    # Collect beam endpoints
    beam_ends: list[tuple[float, float]] = []
    for m in members:
        if m.get("type") == "beam" and m.get("bx1") is not None:
            beam_ends.append((m["bx1"] * page_w, m["by1"] * page_h))
            beam_ends.append((m["bx2"] * page_w, m["by2"] * page_h))

    # Existing column positions (already detected)
    existing = [
        (m["x"] * page_w, m["y"] * page_h)
        for m in members if m.get("type") == "column"
    ]

    def _find_convergence(lx: float, ly: float):
        """
        Return (cx, cy) of the strongest beam-endpoint cluster within
        SEARCH_PT of (lx, ly), or None.
        Best cluster = most endpoints; ties broken by proximity to label.
        """
        nearby = [(ex, ey) for ex, ey in beam_ends
                  if math.hypot(ex - lx, ey - ly) < SEARCH_PT]
        if not nearby:
            return None

        # Cluster nearby endpoints
        clusters: list[list[tuple[float, float]]] = []
        for pt in nearby:
            placed = False
            for cl in clusters:
                if math.hypot(pt[0] - cl[0][0], pt[1] - cl[0][1]) < CLUSTER_PT:
                    cl.append(pt)
                    placed = True
                    break
            if not placed:
                clusters.append([pt])

        # Keep clusters with enough beams, sort by count desc then proximity asc
        valid = [cl for cl in clusters if len(cl) >= MIN_BEAMS]
        if not valid:
            return None
        valid.sort(key=lambda cl: (
            -len(cl),
            math.hypot(sum(p[0] for p in cl)/len(cl) - lx,
                       sum(p[1] for p in cl)/len(cl) - ly)
        ))
        best = valid[0]
        return sum(p[0] for p in best) / len(best), sum(p[1] for p in best) / len(best)

    def _find_grid_intersection(lx: float, ly: float):
        """
        Return (gx, gy) of the nearest v_grid × h_grid crossing within
        GRID_SNAP_PT of (lx, ly), or None.
        """
        if not v_grid or not h_grid:
            return None
        gx = min(v_grid, key=lambda x: abs(x - lx))
        gy = min(h_grid, key=lambda y: abs(y - ly))
        if math.hypot(gx - lx, gy - ly) < GRID_SNAP_PT:
            return gx, gy
        return None

    # Read text spans
    added: list[tuple[float, float]] = []
    try:
        td = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    except Exception:
        return members

    for block in td.get("blocks", []):
        bx0, by0, bx1, by1 = block.get("bbox", (0, 0, 0, 0))
        label_cx = (bx0 + bx1) / 2
        label_cy = (by0 + by1) / 2

        # Check if any span in this block matches "COL"
        block_text = " ".join(
            span.get("text", "").strip()
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        ).strip()
        if not _COL_LABEL_RE.match(block_text):
            continue

        # Step 1: find beam convergence near label (raw position)
        conv = _find_convergence(label_cx, label_cy)

        # Step 2: fallback — grid intersection near the label itself
        grid_near_label = _find_grid_intersection(label_cx, label_cy)

        if conv is None and grid_near_label is None:
            print(f"[COLUMNS] COL label at ({label_cx:.0f},{label_cy:.0f}) "
                  f"discarded — no beam convergence or grid intersection found")
            continue

        # Raw position = beam convergence centroid (most accurate when present)
        raw_x, raw_y = conv if conv is not None else grid_near_label

        # ── Grid snap: keep raw + snapped separately ─────────────────────────
        # Only snap when the grid intersection is VERY close to the convergence
        # point (within GRID_SNAP_PT real).  If farther → the column is
        # genuinely off-grid; keep raw coordinate and tag off_grid=True.
        off_grid = True
        snap_x, snap_y = raw_x, raw_y

        if v_grid:
            gx = min(v_grid, key=lambda g: abs(raw_x - g))
            if abs(raw_x - gx) <= GRID_SNAP_PT:
                snap_x = gx
                off_grid = False
        if h_grid:
            gy = min(h_grid, key=lambda g: abs(raw_y - g))
            if abs(raw_y - gy) <= GRID_SNAP_PT:
                snap_y = gy
                off_grid = False

        px, py = snap_x, snap_y   # final placed position

        # Dedup using final position
        if any(math.hypot(px - ex, py - ey) < DEDUP_PT
               for ex, ey in existing + added):
            continue

        # Grid index naming for text-placed columns
        v_idx = sorted(v_grid).index(gx) + 1 if v_grid and 'gx' in locals() and gx in v_grid else "?"
        h_idx = sorted(h_grid).index(gy) + 1 if h_grid and 'gy' in locals() and gy in h_grid else "?"
        grid_ref = f"{v_idx}-{h_idx}" if (v_idx != "?" or h_idx != "?") else None
        pts_pf = (72.0 / max(scale_ratio, 1)) * 12.0

        added.append((px, py))
        members.append({
            "profile": "COL", "type": "column", "length_ft": 0.0,
            "beam_dir": None,
            "bx1": None, "by1": None, "bx2": None, "by2": None,
            # Final (placed) position
            "x":  round(px / page_w, 4), "y":  round(py / page_h, 4),
            "lx": round(px / page_w, 4), "ly": round(py / page_h, 4),
            "sx": round(px / page_w, 4), "sy": round(py / page_h, 4),
            # Raw convergence position (QA field)
            "raw_x": round(raw_x / page_w, 4),
            "raw_y": round(raw_y / page_h, 4),
            "off_grid": off_grid,
            "rotation": 90,
            "w": 0.018, "h": 0.018,
            "color": MEMBER_COLORS["column"], "confirmed": True,
            "is_column": True, "size_unknown": True,
            "source": "col_text_convergence",
            "geometry": {
                "x": round(px / page_w, 4),
                "y": round(py / page_h, 4),
                "raw_x": round(raw_x / page_w, 4),
                "raw_y": round(raw_y / page_h, 4),
                "snap_offset_ft": round(math.hypot(px - raw_x, py - raw_y) / pts_pf, 2) if pts_pf > 0 else 0.0,
                "grid_ref": grid_ref,
                "symbol": "I",
                "depth_in": 12.0,
                "error_flags": [],
            }
        })

    if added:
        print(f"[COLUMNS] emitted {len(added)} COL-text columns "
              f"(scale_ratio={scale_ratio}  SEARCH={20.0}\" real  SNAP={6.0}\" real)")
    return members


# ── Foundation-Anchored Column Propagation ────────────────────────────────────
_FOUNDATION_COLUMNS_CACHE: dict[str, list[dict]] = {}

def clear_foundation_columns_cache():
    """Explicitly clear the in-memory foundation columns cache."""
    _FOUNDATION_COLUMNS_CACHE.clear()

def get_foundation_columns_for_file(filename: str) -> list[dict]:
    """Retrieve foundation plan column definitions strictly for THIS file/drawing."""
    norm_fn = os.path.basename(filename or "").strip().lower()
    if not norm_fn:
        return []
    
    if norm_fn in _FOUNDATION_COLUMNS_CACHE:
        return _FOUNDATION_COLUMNS_CACHE[norm_fn]
    
    # Read directly from local_db.json strictly matching THIS file
    try:
        import json
        local_db_path = os.path.join(BASE_DIR, "local_db.json")
        if os.path.exists(local_db_path):
            with open(local_db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            drawings = data.get("drawings", [])
            target_drawings = [
                d for d in drawings 
                if (norm_fn in (d.get("storage_key") or "").lower() or (d.get("storage_key") or "").lower() in norm_fn or norm_fn in (d.get("filename") or "").lower())
            ]
            if not target_drawings:
                return []
            
            target_d_ids = {d["id"] for d in target_drawings}
            pages = [p for p in data.get("pages", []) if p.get("drawing_id") in target_d_ids]
            f_pages = [p for p in pages if "foundation" in (p.get("name") or "").lower()]
            if not f_pages:
                return []
            
            f_page_ids = {p["id"] for p in f_pages}
            f_cols = []
            for m in data.get("members", []):
                if m.get("page_id") in f_page_ids and (m.get("kind") == "column" or m.get("type") == "column"):
                    geo = m.get("geometry") or {}
                    f_cols.append({
                        "x": geo.get("x") if geo.get("x") is not None else m.get("x"),
                        "y": geo.get("y") if geo.get("y") is not None else m.get("y"),
                        "grid_ref": geo.get("grid_ref"),
                        "symbol": geo.get("symbol", "I"),
                        "profile": m.get("section") or m.get("profile"),
                    })
            if f_cols:
                _FOUNDATION_COLUMNS_CACHE[norm_fn] = f_cols
                return f_cols
    except Exception as exc:
        print(f"[FOUNDATION PROPAGATION] Error reading local_db: {exc}")
    return []


def propagate_foundation_columns(members: list, foundation_cols: list,
                                 v_grid: list, h_grid: list,
                                 v_labels: dict, h_labels: dict,
                                 page_w: float, page_h: float,
                                 scale_ratio: float = 96,
                                 pts_per_foot: float = 0.0,
                                 plan_bounds: tuple = None) -> list:
    """
    Propagate columns from the Foundation Plan onto a Framing Plan sheet.
    The Foundation Plan is the SINGLE SOURCE OF TRUTH for column locations.
    Any loose/imprecise column candidates on the framing plan near a foundation
    column are replaced by the foundation column's exact grid location.
    """
    if not foundation_cols:
        return members

    _ipt = 72.0 / max(scale_ratio, 1)
    SNAP_PT = 36.0 * _ipt  # 3 ft tolerance to align framing candidates with foundation grid
    REPLACE_TOL = 36.0 * _ipt  # 3 ft tolerance for replacing imprecise framing candidates

    # Separate framing plan members into non-columns and columns
    other_members = [m for m in members if m.get("type") != "column"]
    framing_cols = [m for m in members if m.get("type") == "column"]

    # Active Framing Region Bounding Box:
    # Restrict foundation column projection to the active framing region of THIS sheet.
    active_min_x, active_min_y = 0.0, 0.0
    active_max_x, active_max_y = page_w, page_h
    has_framing_envelope = False

    beam_x_pts, beam_y_pts = [], []
    for m in other_members:
        for kx in ("x", "lx", "sx", "bx1", "bx2"):
            if m.get(kx) is not None:
                beam_x_pts.append(m[kx] * page_w)
        for ky in ("y", "ly", "sy", "by1", "by2"):
            if m.get(ky) is not None:
                beam_y_pts.append(m[ky] * page_h)

    if beam_x_pts and beam_y_pts:
        MARGIN_PT = 36.0 * _ipt  # 3 ft margin around framing envelope
        active_min_x = max(0.0, min(beam_x_pts) - MARGIN_PT)
        active_max_x = min(page_w, max(beam_x_pts) + MARGIN_PT)
        active_min_y = max(0.0, min(beam_y_pts) - MARGIN_PT)
        active_max_y = min(page_h, max(beam_y_pts) + MARGIN_PT)
        has_framing_envelope = True

    # Strict Plan Bounds Box
    pb_x0 = plan_bounds[0] if plan_bounds else 0.0
    pb_y0 = plan_bounds[1] if plan_bounds else 0.0
    pb_x1 = plan_bounds[2] if plan_bounds else page_w
    pb_y1 = plan_bounds[3] if plan_bounds else page_h

    # Map grid labels on current sheet: label -> list of coordinates
    label_to_v_grid: dict[str, list[float]] = {}
    for gx, lbl in (v_labels or {}).items():
        k = str(lbl).strip().upper()
        label_to_v_grid.setdefault(k, []).append(gx)

    label_to_h_grid: dict[str, list[float]] = {}
    for gy, lbl in (h_labels or {}).items():
        k = str(lbl).strip().upper()
        label_to_h_grid.setdefault(k, []).append(gy)

    # Guessed profile for framing columns if unlabeled
    _COL_PROFILE_RE = re.compile(r'^(?:W\d{1,2}X\d{1,3}|HSS\d+(?:\.\d+)?X\d+(?:\.\d+)?X[\d./]+|PIPE\S*)$', re.IGNORECASE)
    _col_profile_counts: dict[str, int] = {}
    for m in members:
        prof = (m.get("profile") or "").upper().strip()
        if prof and _COL_PROFILE_RE.match(prof):
            _col_profile_counts[prof] = _col_profile_counts.get(prof, 0) + 1
    _guessed_profile = (max(_col_profile_counts, key=_col_profile_counts.get)
                         if _col_profile_counts else "W12X40")

    projected_cols = []
    used_framing_col_indices = set()

    for f_col in foundation_cols:
        px, py = None, None
        grid_ref = f_col.get("grid_ref")
        is_explicit_grid_match = False
        raw_x_pt = (f_col.get("x") or 0.5) * page_w
        raw_y_pt = (f_col.get("y") or 0.5) * page_h
        
        # Strategy 1: Flexible Grid Reference Matching (e.g. "1-A", "A-1", "1/A", "A/1", "1 A", "A1", "GRID 1-A")
        if grid_ref:
            g_str = str(grid_ref).strip().upper()
            m_grid = re.search(r'([A-Z0-9.]+)\s*[-/_\s]?\s*([A-Z0-9.]+)', g_str)
            if m_grid:
                p1, p2 = m_grid.group(1), m_grid.group(2)
                if p1 in label_to_v_grid and p2 in label_to_h_grid:
                    px = min(label_to_v_grid[p1], key=lambda x: abs(x - raw_x_pt))
                    py = min(label_to_h_grid[p2], key=lambda y: abs(y - raw_y_pt))
                    is_explicit_grid_match = True
                elif p2 in label_to_v_grid and p1 in label_to_h_grid:
                    px = min(label_to_v_grid[p2], key=lambda x: abs(x - raw_x_pt))
                    py = min(label_to_h_grid[p1], key=lambda y: abs(y - raw_y_pt))
                    is_explicit_grid_match = True

        # Strategy 2: Project relative position inside plan bounds and snap to grid
        if px is None or py is None:
            if f_col.get("x") is not None and f_col.get("y") is not None:
                raw_px = f_col["x"] * page_w
                raw_py = f_col["y"] * page_h
                
                # Dynamic snap radius: proportional to bay spacing or default ~6ft
                v_sorted = sorted(v_grid) if v_grid else []
                h_sorted = sorted(h_grid) if h_grid else []
                v_spans = [v_sorted[k+1] - v_sorted[k] for k in range(len(v_sorted)-1)] if len(v_sorted) > 1 else []
                h_spans = [h_sorted[k+1] - h_sorted[k] for k in range(len(h_sorted)-1)] if len(h_sorted) > 1 else []
                v_bay = (sum(v_spans) / len(v_spans)) if v_spans else 72.0
                h_bay = (sum(h_spans) / len(h_spans)) if h_spans else 72.0
                
                GRID_SNAP_X = max(SNAP_PT, v_bay * 0.45)
                GRID_SNAP_Y = max(SNAP_PT, h_bay * 0.45)
                
                gx_match = min(v_grid, key=lambda g: abs(raw_px - g)) if v_grid else None
                gy_match = min(h_grid, key=lambda g: abs(raw_py - g)) if h_grid else None
                
                if gx_match is not None and abs(raw_px - gx_match) <= GRID_SNAP_X and gy_match is not None and abs(raw_py - gy_match) <= GRID_SNAP_Y:
                    px = gx_match
                    py = gy_match

        if px is None or py is None:
            continue

        # Strict Plan Box Filter: Never place any column outside plan_bounds (drawing box)
        if not (pb_x0 - 5.0 <= px <= pb_x1 + 5.0 and pb_y0 - 5.0 <= py <= pb_y1 + 5.0):
            continue

        # Universal Framing Envelope & Connectivity Gate
        if has_framing_envelope:
            if not (active_min_x <= px <= active_max_x and active_min_y <= py <= active_max_y):
                continue

        CONNECT_RADIUS_PT = 72.0 * _ipt  # ~6 ft connectivity search radius (covers corner spandrels)
        has_local_framing = False
        for m in other_members:
            # Check member endpoints / midpoints
            for kx, ky in (("x", "y"), ("lx", "ly"), ("sx", "sy"), ("bx1", "by1"), ("bx2", "by2")):
                mx_val, my_val = m.get(kx), m.get(ky)
                if mx_val is not None and my_val is not None:
                    if math.hypot(px - mx_val * page_w, py - my_val * page_h) <= CONNECT_RADIUS_PT:
                        has_local_framing = True
                        break
            if has_local_framing:
                break
            # Check beam centerline segment distance
            bx1, by1 = m.get("bx1"), m.get("by1")
            bx2, by2 = m.get("bx2"), m.get("by2")
            if bx1 is not None and by1 is not None and bx2 is not None and by2 is not None:
                x1, y1 = bx1 * page_w, by1 * page_h
                x2, y2 = bx2 * page_w, by2 * page_h
                dx = x2 - x1
                dy = y2 - y1
                l2 = dx * dx + dy * dy
                if l2 > 0:
                    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
                    proj_x = x1 + t * dx
                    proj_y = y1 + t * dy
                    if math.hypot(px - proj_x, py - proj_y) <= CONNECT_RADIUS_PT:
                        has_local_framing = True
                        break

        # Universal rule: project if matched by explicit grid ref OR if local framing exists nearby
        if other_members and not (has_local_framing or is_explicit_grid_match):
            continue

        # Find any imprecise framing column near this foundation column and consume/replace it
        matched_profile = f_col.get("profile") or _guessed_profile
        for idx, fc in enumerate(framing_cols):
            if idx in used_framing_col_indices:
                continue
            fc_x = fc["x"] * page_w
            fc_y = fc["y"] * page_h
            if math.hypot(px - fc_x, py - fc_y) <= REPLACE_TOL:
                used_framing_col_indices.add(idx)
                if fc.get("profile") and fc["profile"] != "COL":
                    matched_profile = fc["profile"]

        # Add the authoritative foundation column at (px, py) with point coordinates
        norm_x = round(px / page_w, 4)
        norm_y = round(py / page_h, 4)
        projected_cols.append({
            "profile": matched_profile,
            "type": "column",
            "length_ft": 0.0,
            "beam_dir": None,
            "bx1": norm_x,
            "by1": norm_y,
            "bx2": norm_x,
            "by2": norm_y,
            "x": norm_x,
            "y": norm_y,
            "lx": norm_x,
            "ly": norm_y,
            "sx": norm_x,
            "sy": norm_y,
            "rotation": 0,
            "source": "foundation_projected",
            "status": "active",
            "geometry": {
                "x": norm_x,
                "y": norm_y,
                "raw_x": norm_x,
                "raw_y": norm_y,
                "bx1": norm_x,
                "by1": norm_y,
                "bx2": norm_x,
                "by2": norm_y,
                "grid_ref": grid_ref,
                "symbol": "I",
                "category": "steel_column",
                "projected_from_foundation": True,
                "error_flags": [],
            },
            "w": 0.02, "h": 0.02,
            "color": MEMBER_COLORS["column"],
            "confirmed": True,
            "is_column": True,
            "size_unknown": False if matched_profile else True,
        })

    # Combine non-columns + projected foundation columns
    result_members = other_members + projected_cols
    if projected_cols:
        print(f"[FOUNDATION PROPAGATION] Projected {len(projected_cols)} foundation columns onto framing plan (replaced {len(used_framing_col_indices)} imprecise framing columns)")

    return result_members


def clean_column_lines(v_grid, h_grid, column_symbols, tol=8.0):
    """Build a CLEAN column-centre set (X for vertical lines, Y for horizontal).

    Per the special rule "columns repeat at grid intersections": a real column
    line carries MULTIPLE column symbols at the same X (or Y).  So we keep the
    grid lines PLUS only the symbol positions where ≥2 symbols align — scattered
    single false marks (connection details mistaken for columns) are dropped —
    then merge anything within `tol`.  This removes the false closely-spaced
    clusters that made the column-aware logic leak.
    """
    def _aligned(vals, min_n=2):
        out, cur = [], []
        for v in sorted(vals):
            if not cur or v - cur[-1] <= tol:
                cur.append(v)
            else:
                if len(cur) >= min_n:
                    out.append(sum(cur) / len(cur))
                cur = [v]
        if cur and len(cur) >= min_n:
            out.append(sum(cur) / len(cur))
        return out

    def _merge(vals, m=8.0):
        out = []
        for v in sorted(vals):
            if not out or abs(v - out[-1]) > m:
                out.append(v)
            else:
                out[-1] = (out[-1] + v) / 2.0
        return out

    sx = _aligned([s["cx"] for s in (column_symbols or [])])
    sy = _aligned([s["cy"] for s in (column_symbols or [])])
    cx = _merge([float(g) for g in (v_grid or [])] + sx)
    cy = _merge([float(g) for g in (h_grid or [])] + sy)
    return cx, cy


def trim_beam_overshoot(members, page_w, page_h, pts_per_foot,
                        col_x=None, col_y=None):
    """Trim a beam endpoint back to the perpendicular beam it frames into.

    A secondary beam frames into a girder (a perpendicular beam) and STOPS at
    its side — it must not pass through it.  For each beam endpoint, if a roughly
    perpendicular beam crosses the beam's axis just INSIDE the endpoint (so the
    beam overshoots that crossing by a small amount), pull the endpoint back to
    the crossing.  Only ever SHORTENS a beam, never lengthens it.

    COLUMN-AWARE: an endpoint sitting at a real COLUMN (from the CLEAN column set)
    is left alone — the beam reaches column-centre to column-centre there, even
    if a girder crosses just before the column.  Only girder-overshoots with NO
    column at the end are trimmed.
    """
    ppf = pts_per_foot if pts_per_foot > 0 else 9.0
    MAX_TRIM = 6.0 * ppf      # only trim overshoots up to ~6 ft (not real spans)
    MIN_TRIM = 0.7 * ppf      # ignore <0.7 ft (that's a normal connection gap)
    PERP_DOT = 0.5            # |cos| < 0.5  → >60° apart  → perpendicular-ish
    COL_ZONE = 1.8 * ppf      # endpoint within this of a column ⇒ it's AT a column

    _cx = sorted(col_x or [])
    _cy = sorted(col_y or [])

    def _at_col(v, cols):
        return bool(cols) and min(abs(v - c) for c in cols) < COL_ZONE

    segs = []
    for m in members:
        if m.get("type") == "beam" and m.get("bx1") is not None:
            segs.append((m, m["bx1"] * page_w, m["by1"] * page_h,
                         m["bx2"] * page_w, m["by2"] * page_h))

    # Outermost column-line bounds: a beam must not extend beyond the last
    # detected column line.  This catches CMU-wall pockets and curtain-wall
    # edges where no perpendicular beam exists to trigger the main trim.
    _cx_min = min(_cx) if _cx else None
    _cx_max = max(_cx) if _cx else None
    _cy_min = min(_cy) if _cy else None
    _cy_max = max(_cy) if _cy else None
    EDGE_TOL = COL_ZONE * 0.5            # tightened: only tiny cantilever gap allowed
    _n_b2b = 0                          # diagnostic: count of beams trimmed

    for m, ax1, ay1, ax2, ay2 in segs:
        L = math.hypot(ax2 - ax1, ay2 - ay1)
        if L < 1:
            continue
        ux, uy = (ax2 - ax1) / L, (ay2 - ay1) / L
        _is_h = abs(ux) >= abs(uy)
        _A_at_col = _at_col(ax1 if _is_h else ay1, _cx if _is_h else _cy)
        _B_at_col = _at_col(ax2 if _is_h else ay2, _cx if _is_h else _cy)
        new_t0, new_tL = 0.0, L

        # ── beam-to-beam trim (original logic) ───────────────────────────────
        for (n, bx1, by1, bx2, by2) in segs:
            if n is m:
                continue
            bL = math.hypot(bx2 - bx1, by2 - by1)
            if bL < 1:
                continue
            vx, vy = (bx2 - bx1) / bL, (by2 - by1) / bL
            if abs(ux * vx + uy * vy) > PERP_DOT:
                continue                       # not perpendicular enough
            den = ux * vy - uy * vx
            if abs(den) < 1e-6:
                continue
            t = ((bx1 - ax1) * vy - (by1 - ay1) * vx) / den
            u = ((bx1 - ax1) * uy - (by1 - ay1) * ux) / den
            if not (-6.0 <= u <= bL + 6.0):
                continue                       # crossing not on the perpendicular beam
            if (not _B_at_col) and MIN_TRIM < (L - t) <= MAX_TRIM and t > L * 0.5:
                new_tL = max(min(new_tL, t), L - MAX_TRIM)
            if (not _A_at_col) and MIN_TRIM < t <= MAX_TRIM and t < L * 0.5:
                new_t0 = min(max(new_t0, t), MAX_TRIM)

        # ── edge-boundary clamp: clamp to outermost column line ───────────────
        # Beyond the OUTERMOST detected column line there is provably no structure
        # to frame into, so ANY endpoint protruding past it (more than EDGE_TOL)
        # is pure overshoot — clamp it straight back to that line with NO MAX_TRIM
        # cap.  This is what kills the perimeter overshoot (corner/edge beams that
        # stick out >6 ft past the last column, which the girder trim's 6 ft cap
        # let through).  The girder trim above keeps its cap because a long real
        # span CAN exist between two interior girders; out here it cannot.  A real
        # cantilever overhang stays within EDGE_TOL and is left alone.
        if _is_h:
            if _cx_min is not None and ax1 < _cx_min - EDGE_TOL and not _A_at_col:
                t_edge = _cx_min - ax1
                if t_edge > MIN_TRIM:
                    new_t0 = max(new_t0, t_edge)
            if _cx_max is not None and ax2 > _cx_max + EDGE_TOL and not _B_at_col:
                t_edge = L - (_cx_max - ax1)
                if t_edge > MIN_TRIM:
                    new_tL = min(new_tL, L - t_edge)
        else:
            if _cy_min is not None and ay1 < _cy_min - EDGE_TOL and not _A_at_col:
                t_edge = _cy_min - ay1
                if t_edge > MIN_TRIM:
                    new_t0 = max(new_t0, t_edge)
            if _cy_max is not None and ay2 > _cy_max + EDGE_TOL and not _B_at_col:
                t_edge = L - (_cy_max - ay1)
                if t_edge > MIN_TRIM:
                    new_tL = min(new_tL, L - t_edge)
        # Safety: never let the combined trims collapse a beam to a sliver.  If
        # they would leave less than a real minimum span (3 ft), the outermost-
        # column estimate is more likely wrong than the beam — leave it untouched.
        MIN_SPAN = 3.0 * ppf
        if (new_t0 > 0 or new_tL < L) and (new_tL - new_t0) >= MIN_SPAN:
            nx1, ny1 = ax1 + ux * new_t0, ay1 + uy * new_t0
            nx2, ny2 = ax1 + ux * new_tL, ay1 + uy * new_tL
            m["bx1"] = round(nx1 / page_w, 4); m["by1"] = round(ny1 / page_h, 4)
            m["bx2"] = round(nx2 / page_w, 4); m["by2"] = round(ny2 / page_h, 4)
            m["x"] = round((nx1 + nx2) / 2 / page_w, 4)
            m["y"] = round((ny1 + ny2) / 2 / page_h, 4)
            m["length_ft"] = round(math.hypot(nx2 - nx1, ny2 - ny1) / ppf, 1)
            _n_b2b += 1
    print(f"[TRIM] columns: {len(_cx)} X / {len(_cy)} Y  |  beams trimmed: {_n_b2b}")
    return members


def align_beam_centerlines_2d(members, page_w, page_h, pts_per_foot):
    """Align horizontal and vertical beams to a consensus centerline.

    Nearly collinear beams are aligned to the same X (vertical) or Y (horizontal) coordinate.
    This corrects drawing/OCR offset issues so they snap correctly to supports.
    """
    if not members:
        return members
    ppf = pts_per_foot if pts_per_foot > 0 else 9.0

    beams = []
    other = []
    for m in members:
        if m.get("type") == "beam" and m.get("bx1") is not None:
            beams.append(m)
        else:
            other.append(m)

    # Classify as horizontal/vertical
    h_beams = []
    v_beams = []
    skewed = []

    for m in beams:
        x1, y1 = m["bx1"] * page_w, m["by1"] * page_h
        x2, y2 = m["bx2"] * page_w, m["by2"] * page_h
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1.0:
            skewed.append(m)
            continue
        ux, uy = dx / L, dy / L
        if abs(ux) >= 0.98: # horizontal-ish
            h_beams.append((m, x1, y1, x2, y2, L, ux, uy))
        elif abs(uy) >= 0.98: # vertical-ish
            v_beams.append((m, x1, y1, x2, y2, L, ux, uy))
        else:
            skewed.append(m)

    # Helper to check collinearity of 2D lines
    def are_collinear_2d(x1, y1, x2, y2, L1, ux1, uy1,
                         b_x1, b_y1, b_x2, b_y2, L2, ux2, uy2):
        dot = abs(ux1 * ux2 + uy1 * uy2)
        if dot < 0.999: # angle tolerance ~2.5 deg (cos(2.5) = 0.999)
            return False
        # Perp distance: perpendicular to line 1
        px, py = -uy1, ux1
        dist = abs((b_x1 - x1) * px + (b_y1 - y1) * py)
        if dist > 1.5 * ppf: # 1.5 ft tolerance
            return False
        return True

    # Group collinear
    def group_collinear(beam_tuples):
        groups = []
        used = set()
        for i, b1 in enumerate(beam_tuples):
            if i in used: continue
            group = [b1]
            used.add(i)
            for j, b2 in enumerate(beam_tuples):
                if j in used: continue
                if are_collinear_2d(b1[1], b1[2], b1[3], b1[4], b1[5], b1[6], b1[7],
                                    b2[1], b2[2], b2[3], b2[4], b2[5], b2[6], b2[7]):
                    group.append(b2)
                    used.add(j)
            groups.append(group)
        return groups

    h_groups = group_collinear(h_beams)
    v_groups = group_collinear(v_beams)

    # Align horizontal groups
    h_aligned = 0
    for group in h_groups:
        if len(group) < 2: continue
        total_l = sum(b[5] for b in group)
        weighted_y = sum((b[2] + b[4]) / 2.0 * b[5] for b in group)
        consensus_y = weighted_y / total_l
        for b, x1, y1, x2, y2, L, ux, uy in group:
            b["by1"] = round(consensus_y / page_h, 4)
            b["by2"] = round(consensus_y / page_h, 4)
            b["y"] = round(consensus_y / page_h, 4)
            h_aligned += 1

    # Align vertical groups
    v_aligned = 0
    for group in v_groups:
        if len(group) < 2: continue
        total_l = sum(b[5] for b in group)
        weighted_x = sum((b[1] + b[3]) / 2.0 * b[5] for b in group)
        consensus_x = weighted_x / total_l
        for b, x1, y1, x2, y2, L, ux, uy in group:
            b["bx1"] = round(consensus_x / page_w, 4)
            b["bx2"] = round(consensus_x / page_w, 4)
            b["x"] = round(consensus_x / page_w, 4)
            v_aligned += 1

    if h_aligned or v_aligned:
        print(f"[ALIGN] aligned {h_aligned} horizontal and {v_aligned} vertical beam centerlines")

    res_beams = [b[0] for b in h_beams] + [b[0] for b in v_beams] + skewed
    return res_beams + other


def snap_beam_ends_to_supports(members, all_struct_lns, col_x, col_y,
                               page_w, page_h, pts_per_foot):
    """UNIVERSAL endpoint rule: a beam runs SUPPORT-to-SUPPORT.

    Real framing data shows ~70 % of beams have NO column on their body — they
    frame girder-to-girder or girder-to-column.  So an endpoint must terminate
    at the nearest PERPENDICULAR structural line it reaches — a column grid line
    OR a crossing girder (a perpendicular drawn beam line) — and STOP there.

    For each endpoint we look at every perpendicular support crossing within a
    search window and snap to the one nearest that endpoint.  This both TRIMS
    overshoot (endpoint sits past the support → pull in) and CLOSES short gaps
    (endpoint stops short of the support → push out) — symmetric, exactly how a
    correctly-drawn labeled girder already terminates.  This is what makes the
    overlay "touch the perpendicular line and stop" on every beam, labeled or not.

    Safety: never collapses a beam below MIN_SPAN; only moves an endpoint when a
    genuine perpendicular support exists within the window (otherwise left as-is).
    """
    if not members:
        return members
    ppf      = pts_per_foot if pts_per_foot > 0 else 9.0
    # Asymmetric window.  Trimming INWARD is safe to do generously: when a beam
    # overshoots its support the gap beyond the support is empty, so the nearest
    # crossing found inward IS the true support even for big overshoots.  EXTENDING
    # outward is riskier (could grab a far line), so keep it short.
    IN_WIN   = 8.0  * ppf     # trim overshoot up to ~8 ft inward to a support without truncating continuous girders
    OUT_WIN  = 3.0  * ppf     # extend a short end only up to ~3 ft to a support
    MIN_SPAN = 3.0  * ppf     # never trim a beam shorter than a real minimum span
    PERP_DOT = 0.55           # |cos| < 0.55  → >56°  → perpendicular-ish
    cols_x   = sorted(col_x or [])
    cols_y   = sorted(col_y or [])

    for m in members:
        if m.get("type") != "beam" or m.get("bx1") is None:
            continue
        x1 = m["bx1"] * page_w; y1 = m["by1"] * page_h
        x2 = m["bx2"] * page_w; y2 = m["by2"] * page_h
        L  = math.hypot(x2 - x1, y2 - y1)
        if L < 1:
            continue
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        # Skip SKEWED / diagonal beams.  The column-grid crossings below assume a
        # rectangular grid; on a skewed framing plan they snap a diagonal endpoint
        # to a wrong grid intersection and distort the span (the angle stays right
        # but the line gets the wrong length/ends).  The matcher already placed the
        # diagonal overlay on its true drawn line — leave it exactly as drawn.
        if not (abs(ux) < 0.09 or abs(uy) < 0.09):    # >~5° off both axes → diagonal
            continue
        is_h   = abs(ux) >= abs(uy)

        cross = []   # parametric t along the axis (from endpoint A) of each support crossing

        # 1) Column grid lines perpendicular to the beam (centre-to-centre spans).
        if is_h and abs(ux) > 1e-6:
            cross += [(cx - x1) / ux for cx in cols_x]
        elif (not is_h) and abs(uy) > 1e-6:
            cross += [(cy - y1) / uy for cy in cols_y]

        # 2) Perpendicular drawn structural lines (girders) — the support for the
        #    ~70 % of beams that DON'T land on a column.  Crossing must fall on the
        #    girder's actual body (not its infinite extension).
        for (sx1, sy1, sx2, sy2, _l) in (all_struct_lns or []):
            sdx, sdy = sx2 - sx1, sy2 - sy1
            sl = math.hypot(sdx, sdy)
            if sl < 1:
                continue
            vx, vy = sdx / sl, sdy / sl
            if abs(ux * vx + uy * vy) > PERP_DOT:
                continue                                   # not perpendicular
            den = ux * vy - uy * vx
            if abs(den) < 1e-6:
                continue
            t = ((sx1 - x1) * vy - (sy1 - y1) * vx) / den  # param along beam
            u = ((sx1 - x1) * uy - (sy1 - y1) * ux) / den  # param along girder
            if -6.0 <= u <= sl + 6.0:                      # crossing on girder body
                cross.append(t)

        # endpoint A (t=0): trim inward (t>0) up to IN_WIN, extend outward (t<0)
        # up to OUT_WIN; endpoint B (t=L): trim inward (t<L) up to IN_WIN, extend
        # outward (t>L) up to OUT_WIN.  Pick the support crossing nearest the end.
        near0 = [t for t in cross if -OUT_WIN <= t <= IN_WIN] if cross else []
        near1 = [t for t in cross if L - IN_WIN <= t <= L + OUT_WIN] if cross else []
        new0 = min(near0, key=lambda t: abs(t))       if near0 else 0.0
        new1 = min(near1, key=lambda t: abs(t - L))   if near1 else L

        # ── Drawn-steel clamp ────────────────────────────────────────────────
        # The overlay must not extend beyond the ACTUAL drawn steel line it traces.
        # PAD = 0.5 ft (6 inches) for physical column/beam seat connection tolerance.
        PAD = 0.5 * ppf
        px, py = -uy, ux
        d_ts = []
        for (sx1, sy1, sx2, sy2, _l) in (all_struct_lns or []):
            sdx, sdy = sx2 - sx1, sy2 - sy1
            sl = math.hypot(sdx, sdy)
            if sl < 1:
                continue
            if abs((sdx * ux + sdy * uy) / sl) < 0.97:        # not parallel
                continue
            mx, my = (sx1 + sx2) / 2, (sy1 + sy2) / 2
            if abs((mx - x1) * px + (my - y1) * py) > 6.0:     # not collinear
                continue
            t1 = (sx1 - x1) * ux + (sy1 - y1) * uy
            t2 = (sx2 - x1) * ux + (sy2 - y1) * uy
            if max(t1, t2) < -8 or min(t1, t2) > L + 8:        # doesn't overlap body
                continue
            d_ts += [t1, t2]
        if d_ts:
            new0 = max(new0, min(d_ts) - PAD)     # don't start before drawn steel + PAD
            new1 = min(new1, max(d_ts) + PAD)     # don't end past drawn steel + PAD

        if new1 - new0 < MIN_SPAN or (abs(new0) < 1e-6 and abs(new1 - L) < 1e-6):
            continue

        nx1, ny1 = x1 + ux * new0, y1 + uy * new0
        nx2, ny2 = x1 + ux * new1, y1 + uy * new1

        # Clamping to building grid boundary to prevent perimeter overshoot
        if cols_x and is_h:
            min_gx, max_gx = min(cols_x) - 4.0, max(cols_x) + 4.0
            nx1 = max(min_gx, min(max_gx, nx1))
            nx2 = max(min_gx, min(max_gx, nx2))
        elif cols_y and (not is_h):
            min_gy, max_gy = min(cols_y) - 4.0, max(cols_y) + 4.0
            ny1 = max(min_gy, min(max_gy, ny1))
            ny2 = max(min_gy, min(max_gy, ny2))

        m["bx1"] = round(nx1 / page_w, 4); m["by1"] = round(ny1 / page_h, 4)
        m["bx2"] = round(nx2 / page_w, 4); m["by2"] = round(ny2 / page_h, 4)
        m["x"]   = round((nx1 + nx2) / 2 / page_w, 4)
        m["y"]   = round((ny1 + ny2) / 2 / page_h, 4)
        m["length_ft"] = round(math.hypot(nx2 - nx1, ny2 - ny1) / ppf, 1)
    return members


def collect_line_widths(page, plan_bounds):
    """Collect drawn SOLID line segments with their stroke WIDTH.

    Returns [(x1, y1, x2, y2, length, width), ...] inside (or near) the plan.

    DASHED lines (curtain-wall boundaries, hidden conditions, reference lines,
    stair-symbol diagonals drawn dashed) are excluded.  Structural members are
    always drawn as SOLID lines; dashed lines are annotations or boundaries.
    """
    out = []
    bx0, by0, bx1, by1 = plan_bounds
    try:
        for d in page.get_drawings():
            # Skip dashed / dotted paths.  PyMuPDF reports solid lines as
            # dashes="" or "[] 0"; anything else is a dash pattern.
            dashes = str(d.get("dashes") or "").strip()
            if dashes and dashes not in ("[] 0", "[] 0.0", "[]"):
                continue                            # dashed → skip
            w = d.get("width")
            wv = float(w) if w is not None else 0.5
            for it in d.get("items", []):
                if it[0] != "l":
                    continue
                try:
                    p1, p2 = it[1], it[2]
                    ln = math.hypot(p2.x - p1.x, p2.y - p1.y)
                    if ln < 20:
                        continue
                    mx, my = (p1.x + p2.x) / 2, (p1.y + p2.y) / 2
                    if not (bx0 - 300 <= mx <= bx1 + 300 and by0 - 300 <= my <= by1 + 300):
                        continue
                    out.append((p1.x, p1.y, p2.x, p2.y, ln, wv))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def center_beam_overlays(members, lines_w, page_w, page_h):
    """RENDER-ONLY centring (runs AFTER all dedup, so it can never drop a beam).

    The matcher can land on a thin line near the label that sits slightly above
    the actual beam.  Structural beam centrelines are drawn THICK; grid /
    dimension / leader lines are thin.  Here we snap each beam's overlay onto the
    THICKEST parallel drawn line that overlaps its span within the section-depth
    band — i.e. onto the dark beam line itself.  Only the finalised overlay
    (and its chip) is moved; no member is added, removed, or re-deduped.
    """
    if not lines_w:
        return members
    for m in members:
        if m.get("type") != "beam" or m.get("bx1") is None:
            continue
        # Unlabeled candidates are placed at the geometric midpoint between
        # the two detected flange lines — that IS the beam centreline.
        # Snapping to the nearest thick line would move the overlay to one
        # flange (half a section depth off).  The computed midpoint is correct;
        # leave it alone.
        if m.get("unlabeled"):
            continue
        x1 = m["bx1"] * page_w; y1 = m["by1"] * page_h
        x2 = m["bx2"] * page_w; y2 = m["by2"] * page_h
        bdx, bdy = x2 - x1, y2 - y1
        bln = math.hypot(bdx, bdy)
        if bln < 1:
            continue
        ux, uy = bdx / bln, bdy / bln
        px, py = -uy, ux                      # perpendicular
        best_w, best_perp = 0.0, None
        for (qx1, qy1, qx2, qy2, qln, qw) in lines_w:
            if qln < 0.5 * bln:               # must span most of the beam
                continue
            qdx, qdy = qx2 - qx1, qy2 - qy1
            if abs((qdx * ux + qdy * uy) / qln) < 0.97:
                continue                       # not parallel to the beam
            perp = (qx1 - x1) * px + (qy1 - y1) * py
            if abs(perp) > 18.0:               # outside section-depth band
                continue
            qt = ((qx1 + qx2) / 2 - x1) * ux + ((qy1 + qy2) / 2 - y1) * uy
            if not (0.1 * bln <= qt <= 0.9 * bln):
                continue                       # must overlap the span body
            if qw > best_w:
                best_w, best_perp = qw, perp
        # Only snap when a genuinely THICK structural line was found (beam lines
        # are ≥~1 pt; thin grid/dim lines are ~0.25 pt).  On drawings that draw
        # beams thin this never fires — so it can't shift a correct overlay.
        # Unlabeled candidates are themselves the thick line; widen search band
        # so a candidate whose midpoint was detected slightly off still snaps.
        is_unlab = m.get("unlabeled", False)
        perp_band = 28.0 if is_unlab else 18.0
        # Re-scan with the correct band (already scanned above, redo if unlabeled)
        if is_unlab:
            best_w, best_perp = 0.0, None
            for (qx1, qy1, qx2, qy2, qln, qw) in lines_w:
                if qln < 0.4 * bln:
                    continue
                qdx, qdy = qx2 - qx1, qy2 - qy1
                if abs((qdx * ux + qdy * uy) / (qln or 1)) < 0.97:
                    continue
                perp = (qx1 - x1) * px + (qy1 - y1) * py
                if abs(perp) > perp_band:
                    continue
                qt = ((qx1 + qx2) / 2 - x1) * ux + ((qy1 + qy2) / 2 - y1) * uy
                if not (0.05 * bln <= qt <= 0.95 * bln):
                    continue
                if qw > best_w:
                    best_w, best_perp = qw, perp
        min_w = 0.7 if is_unlab else 1.0
        if best_perp is not None and best_w >= min_w and abs(best_perp) > 0.5:
            dx, dy = px * best_perp, py * best_perp
            m["bx1"] = round((x1 + dx) / page_w, 4)
            m["by1"] = round((y1 + dy) / page_h, 4)
            m["bx2"] = round((x2 + dx) / page_w, 4)
            m["by2"] = round((y2 + dy) / page_h, 4)
            if m.get("x") is not None:
                m["x"] = round(m["x"] + dx / page_w, 4)
            if m.get("y") is not None:
                m["y"] = round(m["y"] + dy / page_h, 4)
            # keep label chip (lx/ly) in sync with the centered midpoint
            if m.get("lx") is not None:
                m["lx"] = round(m["lx"] + dx / page_w, 4)
            if m.get("ly") is not None:
                m["ly"] = round(m["ly"] + dy / page_h, 4)
    return members


# ── Request models ────────────────────────────────────────────────────────────
class AnalysisRequest(BaseModel):
    filename:         str
    page_index:       int   = 0
    scale_ratio:      float = None
    ocr_dpi:          int   = 400
    detect_braces:    bool  = True    # run brace classifier layer
    detect_unlabeled: bool  = False   # off by default — enable to show (beam?) candidates

FLOOR_HEIGHT_FT = 14.0   # default storey height used for auto-elevation from page index

class ModelRequest(BaseModel):
    filename:           str
    page_index:         int            = 0
    scale_ratio:        float          = None
    detect_unlabeled:   bool           = False
    # When None, floor_elevation_ft is auto-derived from page_index:
    #   floor_elevation_ft = (page_index + 1) * FLOOR_HEIGHT_FT
    # Set explicitly to override (e.g. floor_elevation_ft=20.0 for a 20ft storey).
    floor_elevation_ft: float | None   = None
    detect_braces:      bool           = False

class SaveProjectRequest(BaseModel):
    name:        str
    filename:    str
    scale:       str   = None
    scale_ratio: int   = None
    members:     list  = []
    page_count:  int   = 1


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    print("===== STEELGENIE BACKEND STARTED =====")

@app.get("/health")
def health():
    return {"status": "ok", "supabase": supabase_client is not None}


def _render_page_pil(file_path: str, page_index: int, max_width: int = 2800) -> PILImage.Image:
    """Render a single PDF page (or image file) to a PIL image capped at max_width."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        doc = fitz.open(file_path)
        pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        pil = PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
    else:
        pil = PILImage.open(file_path).convert("RGB")
    if pil.width > max_width:
        ratio = max_width / pil.width
        pil = pil.resize((max_width, int(pil.height * ratio)), PILImage.LANCZOS)
    return pil


def _pil_to_b64(pil: PILImage.Image, quality: int = 85) -> str:
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    content   = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    MAX_PREVIEW_W  = 2800   # full-size preview width cap
    MAX_THUMB_W    = 220    # sidebar thumbnail width cap

    def _render_page_to_b64(pil_img: "PILImage.Image", max_w: int, quality: int, fmt: str = "JPEG") -> str:
        if pil_img.width > max_w:
            ratio = max_w / pil_img.width
            pil_img = pil_img.resize((max_w, int(pil_img.height * ratio)), PILImage.LANCZOS)
        buf = io.BytesIO()
        if fmt == "PNG":
            pil_img.save(buf, format="PNG")
            return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        pil_img.save(buf, format="JPEG", quality=quality)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    ext = os.path.splitext(file.filename)[1].lower()
    if ext == ".pdf":
        doc        = fitz.open(file_path)
        page_count = len(doc)

        # Full-size preview for page 0 (viewed in the drawing window)
        pix0 = doc[0].get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
        pil0 = PILImage.frombytes("RGB", [pix0.width, pix0.height], pix0.samples)

        # Small thumbnails for every page (sidebar strip)
        page_thumbnails = []
        for i in range(page_count):
            pix_t = doc[i].get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
            pil_t = PILImage.frombytes("RGB", [pix_t.width, pix_t.height], pix_t.samples)
            page_thumbnails.append(_render_page_to_b64(pil_t, MAX_THUMB_W, 70))

        doc.close()
        main_b64 = _render_page_to_b64(pil0, MAX_PREVIEW_W, 85, fmt="PNG")
    else:
        page_count = 1
        pil = PILImage.open(file_path).convert("RGB")
        main_b64 = _render_page_to_b64(pil, MAX_PREVIEW_W, 85, fmt="PNG")
        page_thumbnails = [_render_page_to_b64(
            pil.resize((MAX_THUMB_W, int(pil.height * MAX_THUMB_W / pil.width)), PILImage.LANCZOS), MAX_THUMB_W, 70)]

    return {
        "image":           main_b64,
        "page_count":      page_count,
        "filename":        file.filename,
        "page_thumbnails": page_thumbnails,
    }


@app.get("/page-image/{filename}/{page_index}")
async def get_page_image(filename: str, page_index: int):
    """Return full-size preview for a specific page of an already-uploaded PDF."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(404, "File not found")
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        doc = fitz.open(file_path)
        if page_index < 0 or page_index >= len(doc):
            doc.close()
            raise HTTPException(404, f"Page {page_index} not found (total {len(doc)})")
        pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
        pil = PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
    else:
        if page_index != 0:
            raise HTTPException(404, "Image files have only one page")
        pil = PILImage.open(file_path).convert("RGB")

    MAX_PREVIEW_W = 2800
    if pil.width > MAX_PREVIEW_W:
        r = MAX_PREVIEW_W / pil.width
        pil = pil.resize((MAX_PREVIEW_W, int(pil.height * r)), PILImage.LANCZOS)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {"image": f"data:image/png;base64,{b64}", "page_index": page_index}


@app.post("/analyse")
async def analyse_pdf(req: AnalysisRequest):
    start = time.time()
    try:
        tmp_path = os.path.join(UPLOAD_DIR, req.filename)
        ext      = os.path.splitext(req.filename)[1].lower()

        doc  = fitz.open(tmp_path)
        page = doc[req.page_index]

        # ── Page dimensions ───────────────────────────────────────────────────
        if ext in _IMAGE_EXTS:
            _pil_tmp = PILImage.open(tmp_path)
            page_w   = float(_pil_tmp.width)
            page_h   = float(_pil_tmp.height)
            _pil_tmp.close()
            print(f"[ANALYSE] Image file — using PIL dims {page_w:.0f}x{page_h:.0f}")
        else:
            # ── Rotation handling ─────────────────────────────────────────────
            # PyMuPDF returns text/drawing coordinates in the UNROTATED page
            # space, but page.rect reports the ROTATED (displayed) dimensions.
            # For a 90°/270° rotated page these disagree (width↔height swapped),
            # so every member normalized by page.rect lands in the wrong place
            # (the bottom of the plan falls off the assumed height).
            #
            # Fix: do ALL internal processing in the unrotated space (mediabox
            # dims), which matches the coordinate space the text/lines are in.
            # The final member coordinates are transformed back into the rotated
            # DISPLAY space at the end (see "ROTATION OUTPUT TRANSFORM" below),
            # because the image the frontend shows IS rotated.
            #
            # Rotation 0 → mediabox == rect → behaviour identical to before, so
            # non-rotated drawings are completely unaffected.
            if page.rotation in (90, 270):
                page_w, page_h = page.mediabox.width, page.mediabox.height
            else:
                page_w, page_h = page.rect.width, page.rect.height

        # ── 0. Text extraction (vector embedded OR OCR for raster images) ─────
        text_dict, is_raster = _get_text_dict(page, page_w, page_h)
        print(f"[ANALYSE] is_raster={is_raster}  text_blocks={len(text_dict.get('blocks', []))}")

        # 1. Plan boundary — excludes schedules, notes, title block
        plan_bounds = find_plan_boundary(page, page_w, page_h, text_dict=text_dict)

        # 2. Detect column symbols (I/H shapes in vector paths) — fallback to CV for raster
        # Default False so the raster branch below (which has no text layer
        # to check) safely falls back to framing-plan behavior rather than
        # leaving this undefined.
        _is_foundation_plan = False
        if is_raster:
            column_symbols = []
            try:
                import cv2
                from detection_cv import detect_column_symbols as detect_raster_cols
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                cv_img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
                raw_cv_cols = detect_raster_cols(cv_img)
                img_h, img_w = cv_img.shape[:2]
                scale_x = page_w / img_w
                scale_y = page_h / img_h
                for rc in raw_cv_cols:
                    cx_pix = rc["x"] + rc["w"] / 2
                    cy_pix = rc["y"] + rc["h"] / 2
                    cx_pt = cx_pix * scale_x
                    cy_pt = cy_pix * scale_y
                    w_pt = rc["w"] * scale_x
                    depth_in = w_pt * (req.scale_ratio or 96) / 72.0
                    
                    column_symbols.append({
                        "cx": cx_pt,
                        "cy": cy_pt,
                        "rotation": rc.get("angle", 0),
                        "symbol": "BOX" if rc.get("score", 0.0) < 0.6 else "I",
                        "depth_in": depth_in
                    })
            except Exception as e:
                print(f"[ANALYSE] Raster column CV detection failed: {e}")
        else:
            # Foundation/footing plans mark column bases with an unfilled
            # diamond/square outline (F1, P1, ...), not the solid-black steel
            # column plan mark this detector otherwise looks for -- see
            # detect_column_symbols' is_foundation_plan docstring note.
            _page_text_upper = page.get_text().upper()
            _is_foundation_plan = "FOUNDATION PLAN" in _page_text_upper or "FOUNDATION FRAMING" in _page_text_upper
            column_symbols = detect_column_symbols(page, scale_ratio=req.scale_ratio or 96, is_foundation_plan=_is_foundation_plan,
                                                   plan_bounds=plan_bounds)
        # 1b. Schedule & Key Plan exclusion zones, plus general-notes /
        # legend prose blocks (see detect_notes_text_zones -- same
        # cx/cy-inside-zone filter, so a column mark whose only "evidence"
        # is a mark-shaped fragment inside a paragraph of notes text is
        # dropped exactly like one inside a schedule table already is).
        excluded_zones = detect_schedule_zones(page, plan_bounds, text_dict=text_dict)
        excluded_zones = excluded_zones + detect_notes_text_zones(page, text_dict=text_dict)
        if column_symbols and excluded_zones:
            column_symbols = [
                s for s in column_symbols
                if not any(zx0 <= s["cx"] <= zx1 and zy0 <= s["cy"] <= zy1 for zx0, zy0, zx1, zy1 in excluded_zones)
            ]

        # 3. Grid lines — SECONDARY signal. v_labels/h_labels map each
        # position to its REAL bubble text (e.g. "1", "2.3", "A") read
        # straight off the sheet, when the text-based detection path found
        # it. Geometric fallback paths below (raster morphological / column-
        # symbol-derived) have no text to offer, so they clear the label map
        # for that axis -- callers must treat a missing label as "no real
        # label available" rather than inventing one.
        v_grid, h_grid, v_labels, h_labels = extract_grid_lines(
            page, page_w, page_h, plan_bounds, text_dict=text_dict
        )

        # 3b. For raster images, replace text-derived grid with morphological
        #     line detection: finds the actual drawn structural column lines
        #     (long vertical/horizontal lines spanning ≥40% of the plan).
        if is_raster and ext in _IMAGE_EXTS:
            rv, rh = detect_raster_grid_lines(tmp_path, plan_bounds)
            if rv:
                v_grid = rv
                v_labels = {}
            if rh:
                h_grid = rh
                h_labels = {}

        # 3a-2. Foundation-plan mark-label-proximity filtering, now that the
        # real grid lines are available to derive a bay-relative search
        # radius from -- see filter_foundation_symbols_by_marks() docstring.
        # Must run BEFORE the symbol-derived grid fallback below, so that any
        # remaining false-positive symbols don't get baked into v_grid/h_grid.
        if _is_foundation_plan:
            column_symbols = filter_foundation_symbols_by_marks(
                column_symbols, page, v_grid, h_grid, is_foundation_plan=True
            )

        # 3c. If v_grid or h_grid is empty, derive from column symbol positions.
        #     Vertical framing elevations often have no text grid labels, so
        #     extract_grid_lines returns empty lists.  Column symbol X/Y positions
        #     are reliable substitutes: cluster within 30 pt merge tolerance.
        def _cluster_positions(vals, tol=30.0):
            out = []
            for v in sorted(vals):
                if not out or v - out[-1] > tol:
                    out.append(v)
            return out

        if column_symbols:
            # Only derive grid lines from column symbols inside the main framing plan (exclude right-side details)
            _framing_syms = [
                s for s in column_symbols
                if s["cx"] <= page_w * 0.70 and (not plan_bounds or (plan_bounds[0] <= s["cx"] <= plan_bounds[2] and plan_bounds[1] <= s["cy"] <= plan_bounds[3]))
            ]
            if not v_grid and _framing_syms:
                _sym_xs = [s["cx"] for s in _framing_syms]
                v_grid = _cluster_positions(_sym_xs, tol=30.0)
                if v_grid:
                    print(f"[ANALYSE] v_grid derived from {len(_framing_syms)} framing symbols: "
                          f"{[round(x) for x in v_grid]}")
            if not h_grid and _framing_syms:
                _sym_ys = [s["cy"] for s in _framing_syms]
                h_grid = _cluster_positions(_sym_ys, tol=30.0)
                if h_grid:
                    print(f"[ANALYSE] h_grid derived from {len(_framing_syms)} framing symbols: "
                          f"{[round(y) for y in h_grid]}")

        # 4. Extract profile labels within the plan
        profiles = extract_profiles(page, page_w, page_h, plan_bounds,
                                    text_dict=text_dict)
        print(f"[ANALYSE] Profiles in plan: {len(profiles)}")

        # ── DIAGNOSTIC DUMP ──────────────────────────────────────────────────
        syms_in_plan = [s for s in column_symbols
                        if plan_bounds[0] <= s["cx"] <= plan_bounds[2]
                        and plan_bounds[1] <= s["cy"] <= plan_bounds[3]]
        print(f"\n{'='*60}")
        print(f"[DIAG] Page size      : {page_w:.0f} x {page_h:.0f} pt")
        # Rotation diagnostics: a /Rotate flag makes page.rect dims disagree with
        # the text/drawing coordinate space, mis-normalizing every member.
        try:
            _mb = page.mediabox
            print(f"[DIAG] Page rotation  : {page.rotation}°")
            print(f"[DIAG] MediaBox       : {_mb.width:.0f} x {_mb.height:.0f} pt")
            _all_cy = [p['cy'] for p in profiles] + [s['cy'] for s in column_symbols]
            _all_cx = [p['cx'] for p in profiles] + [s['cx'] for s in column_symbols]
            if _all_cx and _all_cy:
                print(f"[DIAG] Content extent : x=[{min(_all_cx):.0f},{max(_all_cx):.0f}] "
                      f"y=[{min(_all_cy):.0f},{max(_all_cy):.0f}]  "
                      f"(vs page {page_w:.0f}x{page_h:.0f})")
        except Exception as _e:
            print(f"[DIAG] rotation probe failed: {_e}")
        print(f"[DIAG] Raster mode    : {is_raster}")
        print(f"[DIAG] Plan boundary  : x=[{plan_bounds[0]:.0f},{plan_bounds[2]:.0f}] "
              f"y=[{plan_bounds[1]:.0f},{plan_bounds[3]:.0f}]")
        print(f"[DIAG] V grid lines   : {len(v_grid)}  -> {[round(x) for x in v_grid]}")
        print(f"[DIAG] H grid lines   : {len(h_grid)}  -> {[round(y) for y in h_grid]}")
        print(f"[DIAG] Symbols total  : {len(column_symbols)}  "
              f"| inside plan: {len(syms_in_plan)}")
        for s in column_symbols:
            tag = "IN " if (plan_bounds[0] <= s["cx"] <= plan_bounds[2]
                            and plan_bounds[1] <= s["cy"] <= plan_bounds[3]) else "OUT"
            print(f"  [{tag}] cx={s['cx']:.0f}  cy={s['cy']:.0f}")
        print(f"[DIAG] Profiles found : {len(profiles)}")
        for i, p in enumerate(profiles):
            print(f"  [{i:02d}] {p['profile']:14s}  cx={p['cx']:.0f}  cy={p['cy']:.0f}")
        print(f"{'='*60}\n")
        # ─────────────────────────────────────────────────────────────────────

        # 5. Scale → pts per foot (from user-selected drawing scale or auto-detected from page text)
        if req.scale_ratio and req.scale_ratio > 0:
            pts_per_foot = scale_to_pts_per_foot(req.scale_ratio)
        else:
            # Auto-detect architectural scale annotation on this page
            auto_scales = _brace_find_scales(page) if not is_raster else []
            if auto_scales:
                pts_per_foot = auto_scales[0][0]
                print(f"[ANALYSE] Auto-detected drawing scale on page: {pts_per_foot:.2f} pts/ft")
            else:
                pts_per_foot = 9.0  # standard 1/8" = 1'-0" fallback (ratio = 96)
                print(f"[ANALYSE] Default fallback scale: 9.0 pts/ft (1/8\"=1'-0\")")
        print(f"[ANALYSE] scale_ratio={req.scale_ratio}  pts_per_foot={pts_per_foot:.2f}")

        # 6. PRIMARY: match beam centerlines to profile labels
        #    • Vector PDF: read page.get_drawings() — exact mathematical geometry.
        #    • Raster image: render to 300-DPI greyscale and run HoughLinesP.
        #      Before this fix the raster path skipped this step entirely
        #      (beam_line_map = {}), forcing 100 % of beams through the
        #      grid-based fallback which only achieves bay-level precision.
        if is_raster and _RASTER_HOUGH_AVAILABLE and profiles:
            _DPI_HOUGH  = 300
            _PX_PER_PT  = _DPI_HOUGH / 72.0
            _pix        = page.get_pixmap(dpi=_DPI_HOUGH, colorspace=fitz.csGRAY)
            _gray_arr   = np.frombuffer(_pix.samples, dtype=np.uint8).reshape(
                              _pix.height, _pix.width)
            beam_line_map = _detect_beam_lines_raster(
                _gray_arr, profiles, plan_bounds, _PX_PER_PT)
            print(f"[ANALYSE] Raster Hough beam_line_map: {len(beam_line_map)} hits")
            del _pix, _gray_arr   # free memory
        else:
            if is_raster:
                beam_line_map   = {}
                _all_struct_lns = []
            else:
                beam_line_map, _all_struct_lns = detect_beam_lines(
                    page, profiles, plan_bounds,
                    pts_per_foot=pts_per_foot,
                    column_symbols=column_symbols,
                    v_grid=v_grid,
                    h_grid=h_grid)

        # ── Unclaimed / Unlabeled beam detection ──────────────────────────────
        # Detects real drawn structural beams on the blueprint that have no nearby text label
        # (e.g. infill beams, typical filler beams, stair/elevator opening headers).
        # We consider lines in _all_struct_lns that were NOT claimed by any labeled profile.
        if not is_raster and _all_struct_lns and getattr(req, 'detect_unlabeled', False):
            _pb = plan_bounds
            _plan_w = _pb[2] - _pb[0] if _pb else 1000.0
            _plan_h = _pb[3] - _pb[1] if _pb else 1000.0
            _MAX_H_FRAC = 0.85   # F3: H-line must be shorter than 85 % of plan width
            _MAX_V_FRAC = 0.85   # F3: V-line must be shorter than 85 % of plan height
            _DEDUP_R    = 35     # F4: midpoint deduplication radius
            _SYN_CAP    = 300    # F5: capacity cap

            # Collect midpoints of lines already claimed by labeled profiles
            _claimed_mids: list[tuple] = []
            for _p_idx, _hit in beam_line_map.items():
                _claimed_mids.append(((_hit["x1"] + _hit["x2"]) / 2, (_hit["y1"] + _hit["y2"]) / 2))

            _syn_profiles  = []
            _syn_line_map  = {}
            _seen_mids     = list(_claimed_mids)

            for (lx1, ly1, lx2, ly2, ln) in _all_struct_lns:
                if len(_syn_profiles) >= _SYN_CAP:
                    break
                adx = abs(lx2 - lx1)
                ady = abs(ly2 - ly1)

                # F1 — orthogonal or clear diagonal
                if adx > ady * 2:
                    bdir = "H"
                elif ady > adx * 2:
                    bdir = "V"
                elif adx > 25 and ady > 25:
                    bdir = "D"
                else:
                    continue

                # F3 — reject full-plan-width / full-plan-height lines (grid lines)
                if bdir == "H" and adx > _plan_w * 0.50:
                    continue
                if bdir == "V" and ady > _plan_h * 0.50:
                    continue

                # Multi-bay span rejection: an infill beam without text never spans across multiple bays
                if v_grid and len(v_grid) >= 2 and bdir == "H":
                    _max_v_bay = max(v_grid[i+1] - v_grid[i] for i in range(len(v_grid)-1))
                    if adx > _max_v_bay * 1.30:
                        continue
                if h_grid and len(h_grid) >= 2 and bdir == "V":
                    _max_h_bay = max(h_grid[i+1] - h_grid[i] for i in range(len(h_grid)-1))
                    if ady > _max_h_bay * 1.30:
                        continue

                # Discard short ticks / dimension marks / leader arrows (under 3.5 ft real span)
                _min_real_beam_pt = max(30.0, pts_per_foot * 3.5) if pts_per_foot > 0 else 30.0
                if ln < _min_real_beam_pt:
                    continue

                mx = (lx1 + lx2) / 2
                my = (ly1 + ly2) / 2

                # Exclude lines falling inside Key Plan or schedule zones
                if any(zx0 <= mx <= zx1 and zy0 <= my <= zy1 for zx0, zy0, zx1, zy1 in (excluded_zones or [])):
                    continue

                # Discard ANY unlabeled line that lies directly on or near a structural grid line
                if v_grid and bdir == "V" and any(abs(mx - gx) < 14.0 for gx in v_grid):
                    continue
                if h_grid and bdir == "H" and any(abs(my - gy) < 14.0 for gy in h_grid):
                    continue

                # Exclude lines outside the primary structural grid framing envelope (dimension strings, extension lines)
                if v_grid and h_grid:
                    min_gx, max_gx = min(v_grid) - 2.0, max(v_grid) + 2.0
                    min_gy, max_gy = min(h_grid) - 2.0, max(h_grid) + 2.0
                    if not (min_gx <= min(lx1, lx2) and max(lx1, lx2) <= max_gx and
                            min_gy <= min(ly1, ly2) and max(ly1, ly2) <= max_gy):
                        continue

                # F4 — deduplicate against already-claimed beam lines and previously added synthetics
                if any(math.hypot(smx - mx, smy - my) < _DEDUP_R
                       for smx, smy in _seen_mids):
                    continue

                syn_idx = len(profiles) + len(_syn_profiles)
                _syn_profiles.append({
                    "profile":  "?",
                    "cx": mx, "cy": my,
                    "dir_hint": bdir,
                    "bbox_w": 20.0, "bbox_h": 8.0,
                    "unlabeled": True,
                })
                _syn_line_map[syn_idx] = {
                    "x1": lx1, "y1": ly1,
                    "x2": lx2, "y2": ly2,
                    "dir": bdir, "length_pt": ln,
                }
                _seen_mids.append((mx, my))

            if _syn_profiles:
                print(f"[ANALYSE] Extracted {len(_syn_profiles)} unlabeled structural beam lines "
                      f"(alongside {len(profiles)} labeled profiles)")
                profiles.extend(_syn_profiles)
                beam_line_map.update(_syn_line_map)

        # 7. FALLBACK direction detection
        #    • Vector: use adjacent drawn lines via detect_beam_directions().
        #    • Raster:  Hough hits already carry a 'dir' key; OCR rotation hints
        #      (dir_hint) fill in for the remaining unmatched profiles.
        if is_raster:
            # Build beam_dirs from Hough results first, then fill gaps from dir_hint
            beam_dirs: dict[int, str] = {}
            for p_idx, hit in beam_line_map.items():
                beam_dirs[p_idx] = hit["dir"]
            # Any profile not matched by Hough falls back to OCR rotation hint
            for p_idx, p in enumerate(profiles):
                if p_idx not in beam_dirs:
                    beam_dirs[p_idx] = p.get("dir_hint", "H")
            h_hints = sum(1 for d in beam_dirs.values() if d == "H")
            v_hints = sum(1 for d in beam_dirs.values() if d == "V")
            print(f"[ANALYSE] Raster beam_dirs (Hough+hint): H={h_hints}  V={v_hints}")
        else:
            beam_dirs = detect_beam_directions(page, profiles, plan_bounds)

        # 8. Classify and build
        members = build_members(profiles, page_w, page_h,
                                column_symbols=column_symbols,
                                v_grid=v_grid, h_grid=h_grid,
                                pts_per_foot=pts_per_foot,
                                beam_dirs=beam_dirs,
                                beam_line_map=beam_line_map,
                                plan_bounds=plan_bounds,
                                is_vector=not is_raster)

        # Trim beams that overshoot the perpendicular girder/beam they frame
        # into — they must STOP at that connection, not pass through it.
        # Column-aware against a CLEAN column set, so an endpoint AT a real
        # column reaches column-centre while girder-overshoots are trimmed.
        # Only shortens overshoots; never lengthens (so correct spans are safe).
        if not is_raster:
            _ccx, _ccy = clean_column_lines(v_grid, h_grid, column_symbols)
            members = trim_beam_overshoot(members, page_w, page_h, pts_per_foot,
                                          col_x=_ccx, col_y=_ccy)

        # Count columns: emit a column member for each column symbol at a grid
        # intersection (framing-plan columns have no size label of their own).
        _col_scale = req.scale_ratio or 96
        members = emit_symbol_columns(members, column_symbols, v_grid, h_grid,
                                      page_w, page_h, scale_ratio=_col_scale,
                                      pts_per_foot=pts_per_foot, profiles=profiles,
                                      is_foundation_plan=_is_foundation_plan)
        # COL text label columns — framing plans only (placed at beam convergence, not on foundation plans).
        if not _is_foundation_plan:
            members = extract_col_text_columns(page, page_w, page_h, members,
                                               v_grid=v_grid, h_grid=h_grid,
                                               scale_ratio=_col_scale)

        # ── Foundation-Anchored Column Propagation ─────────────────────────────
        _norm_fn = os.path.basename(req.filename).strip().lower()
        if _is_foundation_plan:
            _f_cols = []
            for _m in members:
                if _m.get("type") in ("column", "footing"):
                    _geo = _m.get("geometry") or {}
                    _f_cols.append({
                        "x": _m.get("x"),
                        "y": _m.get("y"),
                        "grid_ref": _geo.get("grid_ref"),
                        "symbol": _geo.get("symbol", "I"),
                        "profile": _m.get("profile"),
                    })
            if _f_cols:
                _FOUNDATION_COLUMNS_CACHE[_norm_fn] = _f_cols
                print(f"[FOUNDATION CACHE] Cached {len(_f_cols)} foundation columns for {_norm_fn}")
        else:
            _f_cols = get_foundation_columns_for_file(req.filename)
            if _f_cols:
                members = propagate_foundation_columns(
                    members, _f_cols, v_grid, h_grid,
                    v_labels, h_labels, page_w, page_h,
                    scale_ratio=_col_scale, pts_per_foot=pts_per_foot,
                    plan_bounds=plan_bounds
                )

        # Synthetic unlabeled candidate generation disabled:
        # Only real Beams, Columns, and Joists are extracted and emitted.
        _lines_w = collect_line_widths(page, plan_bounds) if not is_raster else []

        # Universal endpoint snap: pull EVERY beam end (labeled + unlabeled) to the
        # nearest perpendicular support it reaches — column line OR crossing girder
        # — and stop there.  Trims overshoot and closes short gaps along the axis.
        # Runs after unlabeled detection so candidates terminate like real girders.
        if not is_raster:
            members = align_beam_centerlines_2d(members, page_w, page_h, pts_per_foot)
            _ccx2, _ccy2 = clean_column_lines(v_grid, h_grid, column_symbols)
            members = snap_beam_ends_to_supports(
                members, _all_struct_lns, _ccx2, _ccy2,
                page_w, page_h, pts_per_foot)

        # Render-only: snap EVERY overlay line (labeled + unlabeled candidates)
        # onto the THICK (dark) beam centreline.  Runs LAST so candidates are
        # centred too — they lie ON the beam, not near it.
        if not is_raster:
            members = center_beam_overlays(members, _lines_w, page_w, page_h)

        # Final dedup: drop duplicate overlapping beam overlays left by the
        # labeled + unlabeled passes (keeps labeled over unlabeled, longer over
        # shorter; leaves two distinct labeled beams alone).
        members = dedup_overlapping_beams(members, page_w, page_h, pts_per_foot)

        # ── BRACE EXTRACTION ──────────────────────────────────────────────────
        # Enabled when the BRACE_EXTRACTION env flag is set OR when the caller
        # explicitly passes detect_braces=true in the request body.
        if _BRACE_EXTRACTION_ENABLED or req.detect_braces:
            if _BRACE_EXTRACTION_AVAILABLE:
                try:
                    _bppf          = _brace_ppf(req.scale_ratio) if req.scale_ratio else pts_per_foot
                    _b_candidates  = _brace_extract_diagonals(page, _bppf)
                    _b_ctx, _      = _brace_classify_context(page)
                    _b_scales      = _brace_find_scales(page)
                    # Node extraction now runs for framing_plan too (strict both-
                    # endpoint check in brace_classifier.py Layer 5).
                    from brace_classifier import NODE_CHECK_CONTEXTS as _NODE_CTX
                    _b_nodes       = (
                        _brace_extract_nodes(page, _bppf)
                        if _b_ctx in _NODE_CTX
                        else None
                    )
                    _b_openings    = _brace_extract_openings(page)
                    _b_classified  = _brace_classify(_b_candidates, _b_ctx, _b_scales, _bppf, _b_nodes, _b_openings)
                    _b_classified  = _brace_enrich(_b_classified, page)

                    # Post-enrichment gate: reject diagonals labelled with a
                    # W-section profile.  A W-beam label next to a diagonal line
                    # means the line is a sloped/skewed beam, NOT a structural
                    # brace.  Real braces use HSS / angle (L) / TS / double-L.
                    _W_SECTION_RE = re.compile(r'^W\s*\d{1,3}\s*[Xx]\s*\d', re.I)
                    for _bc in _b_classified:
                        if (_bc.get("confidence") in ("HIGH", "MEDIUM")
                                and _bc.get("section_label")
                                and _W_SECTION_RE.match(_bc["section_label"])):
                            _bc["confidence"]    = "REJECT"
                            _bc["reject_reason"] = f"w_section_label:{_bc['section_label']}"

                    _b_high   = [c for c in _b_classified if c["confidence"] == "HIGH"]
                    _b_medium = [c for c in _b_classified if c["confidence"] == "MEDIUM"]

                    for _bc in (_b_high + _b_medium):
                        members.append({
                            "type":             "brace",
                            "profile":          _bc.get("section_label"),
                            "label":            None,
                            "config":           _bc.get("config", "single_diagonal"),
                            "role":             _bc.get("role", "lateral_unconfirmed"),
                            "detection_method": _bc.get("detection_method", "rules"),
                            "confidence":       _bc["confidence"],
                            "context":          _bc.get("page_context", _b_ctx),
                            "length_ft":        _bc["length_ft"],
                            "angle_deg":        _bc["angle_from_h"],
                            # Normalised fractional coords (0–1) matching beam format
                            "bx1":  round(_bc["x1"] / page_w, 4),
                            "by1":  round(_bc["y1"] / page_h, 4),
                            "bx2":  round(_bc["x2"] / page_w, 4),
                            "by2":  round(_bc["y2"] / page_h, 4),
                            # Midpoint for label placement
                            "x":    round((_bc["x1"] + _bc["x2"]) / 2 / page_w, 4),
                            "y":    round((_bc["y1"] + _bc["y2"]) / 2 / page_h, 4),
                            "lx":   round((_bc["x1"] + _bc["x2"]) / 2 / page_w, 4),
                            "ly":   round((_bc["y1"] + _bc["y2"]) / 2 / page_h, 4),
                            "sx":   round(_bc["x1"] / page_w, 4),
                            "sy":   round(_bc["y1"] / page_h, 4),
                        })

                    print(f"[BRACE] ctx={_b_ctx}  HIGH={len(_b_high)}  "
                          f"MED={len(_b_medium)}  total_candidates={len(_b_classified)}")
                except Exception as _be:
                    print(f"[BRACE] extraction error (non-fatal): {_be}")
            else:
                print("[BRACE] brace_classifier not available — skipping")

        # ── FOUNDATION PLAN: keep ONLY footings + columns ─────────────────────
        # User directive (2026-07-20, repeated and explicit): "from the
        # foundation plan extract only column as well as footing ... don't
        # extract anything like beam, joist from the foundation plan ... mark
        # exactly on the top of the column". A foundation plan's job is to
        # locate footings/piers/columns -- the "beams" the generic detector
        # pulls off it are really the wall/grid/dimension lines, which the
        # user does not want. So on a foundation plan we DISCARD every beam/
        # joist/brace/suggested member the pipeline built, and REPLACE the
        # column/footing set with the grid-intersection detector, which places
        # each marker dead-center on the real footing (the grid intersection,
        # where the sheet itself says every column is centered). Framing plans
        # are completely untouched by this block.
        if _is_foundation_plan and not is_raster:
            try:
                _foots = detect_foundation_footings_grid(
                    page, plan_bounds, scale_ratio=req.scale_ratio or 96)
            except Exception as _fe:
                print(f"[FOUNDATION] grid detector error (non-fatal): {_fe}")
                _foots = []
            if _foots:
                import uuid as _uuid_mod
                _new_members = []
                for _f in _foots:
                    _px, _py = _f["cx"], _f["cy"]
                    _xf = round(_px / page_w, 4)
                    _yf = round(_py / page_h, 4)
                    _grp = str(_uuid_mod.uuid4())
                    # Emit ONLY ONE single clean Column record per footing site
                    _new_members.append({
                        "profile": None, "type": "column", "length_ft": 0.0,
                        "beam_dir": None,
                        "bx1": _xf, "by1": _yf, "bx2": _xf, "by2": _yf,
                        "x": _xf, "y": _yf, "lx": _xf, "ly": _yf,
                        "sx": _xf, "sy": _yf,
                        "rotation": 0, "source": "grid_footing",
                        "status": "need_review",
                        "geometry": {
                            "x": _xf, "y": _yf, "raw_x": _xf, "raw_y": _yf,
                            "bx1": _xf, "by1": _yf, "bx2": _xf, "by2": _yf,
                            "grid_ref": _f["grid_ref"], "symbol": "I",
                            "category": "footing_isolated",
                            "linked_group_id": _grp, "linked_role": "column",
                            "error_flags": [], "guessed": True,
                        },
                        "w": 0.018, "h": 0.018,
                        "color": MEMBER_COLORS["column"],
                        "confirmed": True, "is_column": True, "size_unknown": True,
                    })
                members = _new_members
                print(f"[FOUNDATION] replaced members with {len(_foots)} "
                      f"footing+column pairs (dropped all beams/joists/braces)")
            else:
                # Detector found nothing usable (no clean grid) -- rather than
                # emit the noisy generic output on a foundation plan, keep only
                # whatever real footing/column members the old path produced and
                # still drop the beams/joists/braces the user rejected.
                members = [m for m in members
                           if m.get("type") in ("footing", "column")
                           and m.get("source") != "suggested"]
                print("[FOUNDATION] grid detector empty; kept "
                      f"{len(members)} footing/column members, dropped rest")

        # ── ROTATION OUTPUT TRANSFORM ─────────────────────────────────────────
        # All member coordinates above are fractions of the UNROTATED page
        # space (page_w × page_h = mediabox for rotated pages).  The image the
        # frontend displays is RENDERED ROTATED (get_pixmap applies the page
        # rotation), so we map each fractional coordinate from unrotated space
        # into the rotated DISPLAY space using fitz's own rotation matrix —
        # this is guaranteed to match how the image was rendered (no manual
        # CW/CCW derivation).  Skipped entirely when rotation == 0.
        if not is_raster and page.rotation != 0:
            _rmat = page.rotation_matrix          # unrotated → rotated coords
            _rw   = page.rect.width               # rotated display dims
            _rh   = page.rect.height
            _puw, _puh = page_w, page_h           # unrotated processing dims

            def _rot_frac(fx, fy):
                if fx is None or fy is None:
                    return fx, fy
                _pt = fitz.Point(fx * _puw, fy * _puh) * _rmat
                return round(_pt.x / _rw, 4), round(_pt.y / _rh, 4)

            for _m in members:
                _m["x"],   _m["y"]   = _rot_frac(_m.get("x"),   _m.get("y"))
                _m["lx"],  _m["ly"]  = _rot_frac(_m.get("lx"),  _m.get("ly"))
                _m["sx"],  _m["sy"]  = _rot_frac(_m.get("sx"),  _m.get("sy"))
                _m["bx1"], _m["by1"] = _rot_frac(_m.get("bx1"), _m.get("by1"))
                _m["bx2"], _m["by2"] = _rot_frac(_m.get("bx2"), _m.get("by2"))
                # column/footing members (emit_symbol_columns, build_members'
                # footing split) carry a NESTED "geometry" dict with their own
                # raw_x/raw_y — the true detected symbol center BEFORE grid
                # snapping, independent of x/y. The loop above only rotates
                # top-level fields, so raw_x/raw_y was silently left in the
                # unrotated coordinate space on every page with a PDF rotation
                # flag. The frontend prefers raw_x/raw_y for the marker
                # position and draws a correction line from it to x/y -- with
                # raw_x/raw_y unrotated, markers landed in the wrong spot and
                # the correction lines fanned out wildly across the whole
                # sheet on any rotated page (any PDF, not just one drawing).
                _geo = _m.get("geometry")
                if isinstance(_geo, dict):
                    if _geo.get("raw_x") is not None and _geo.get("raw_y") is not None:
                        _geo["raw_x"], _geo["raw_y"] = _rot_frac(_geo.get("raw_x"), _geo.get("raw_y"))
                    if _geo.get("x") is not None and _geo.get("y") is not None:
                        _geo["x"], _geo["y"] = _rot_frac(_geo.get("x"), _geo.get("y"))
            print(f"[ANALYSE] Applied {page.rotation}° rotation transform "
                  f"to {len(members)} members (unrotated {_puw:.0f}x{_puh:.0f} "
                  f"-> display {_rw:.0f}x{_rh:.0f})")

        # ── Physical length enforcement ───────────────────────────────────────
        # Ensure EVERY member with endpoints (bx1,by1 -> bx2,by2) has an exact,
        # mathematically verified length_ft calculated from true drawing scale.
        _calc_w = page.rect.width if (not is_raster and page.rotation in (90, 270)) else page_w
        _calc_h = page.rect.height if (not is_raster and page.rotation in (90, 270)) else page_h
        _eff_ppf = pts_per_foot if (pts_per_foot and pts_per_foot > 0) else 9.0

        for _m in members:
            _bx1, _by1 = _m.get("bx1"), _m.get("by1")
            _bx2, _by2 = _m.get("bx2"), _m.get("by2")
            if _bx1 is not None and _by1 is not None and _bx2 is not None and _by2 is not None:
                _dx = (_bx2 - _bx1) * _calc_w
                _dy = (_by2 - _by1) * _calc_h
                _dist_pt = math.hypot(_dx, _dy)
                if _dist_pt > 5.0 and _m.get("type") != "column":
                    _m["length_ft"] = round(_dist_pt / _eff_ppf, 1)

        summary = build_summary(members)

        counts  = {t: summary[t] for t in ["column", "beam", "vertical_brace"]}
        elapsed = round(time.time() - start, 2)
        method  = ("pymupdf+ocr+hough+grid" if (is_raster and _RASTER_HOUGH_AVAILABLE)
                   else "pymupdf+ocr+grid"   if is_raster
                   else "pymupdf+symbols+grid")
        print(f"[ANALYSE] {len(members)} members in {elapsed}s — {counts}")

        doc.close()

        # Real grid bubble labels (e.g. "1", "2.3", "A") read straight off
        # this sheet, as fractions of page width/height -- same convention as
        # members' bx1/by1/bx2/by2 -- so the multi-sheet registration layer
        # can persist the sheet's ACTUAL grid instead of guessing sequential
        # numbers. Entries with no real detected label (geometric-fallback
        # positions) are still included with label=None so callers know a
        # line exists there even without a confirmed name.
        grid_bubbles = {
            "v": [{"position": round(x / page_w, 4), "label": v_labels.get(x)} for x in (v_grid or [])],
            "h": [{"position": round(y / page_h, 4), "label": h_labels.get(y)} for y in (h_grid or [])],
        }

        try:
            from app.engineering.grid_geometry_pass import (
                run_deterministic_geometry_pass,
                to_frontend_dimension_lines,
                to_frontend_work_point,
                snap_members_to_grid_bays,
            )
            _override_ppf = pts_per_foot if (req.scale_ratio and req.scale_ratio > 0) else None
            _geom_results = run_deterministic_geometry_pass(
                tmp_path, page_number=req.page_index, override_pts_per_foot=_override_ppf
            )
            grid_dimensions = to_frontend_dimension_lines(_geom_results)
            work_point = to_frontend_work_point(_geom_results)

            # Snap member lengths, coordinates, and labels to verified grid bays & grid intersections
            _snapped_cnt = snap_members_to_grid_bays(
                members, _geom_results, _calc_w, _calc_h, _eff_ppf
            )
            members = dedup_overlapping_beams(members, _calc_w, _calc_h, _eff_ppf)
            print(f"[ANALYSE] grid_dimensions via run_deterministic_geometry_pass: {len(grid_dimensions)} lines (snapped {_snapped_cnt} members to grid bays)")

            # Update grid_bubbles with verified vector grids so DB stores accurate sub-grids
            if _geom_results.get("vertical_grids") and _geom_results.get("horizontal_grids"):
                grid_bubbles = {
                    "v": [{"position": round(g["x"] / _calc_w, 4), "label": g["label"]} for g in _geom_results["vertical_grids"]],
                    "h": [{"position": round(g["y"] / _calc_h, 4), "label": g["label"]} for g in _geom_results["horizontal_grids"]],
                }
        except Exception as _geom_exc:
            import traceback
            print(f"[ANALYSE] run_deterministic_geometry_pass failed for page={req.page_index}: {_geom_exc} — falling back to legacy extract_grid_dimensions")
            traceback.print_exc()
            grid_dimensions = extract_grid_dimensions(
                page, page_w, page_h, plan_bounds,
                v_grid, h_grid, v_labels, h_labels, pts_per_foot,
                text_dict=text_dict
            )
            try:
                vg = [{"x": x, "label": str(lbl)} for x, lbl in zip(v_grid, v_labels)] if (v_grid and v_labels) else []
                hg = [{"y": y, "label": str(lbl)} for y, lbl in zip(h_grid, h_labels)] if (h_grid and h_labels) else []
                if vg and hg:
                    from app.engineering.grid_geometry_pass import to_frontend_work_point
                    work_point = to_frontend_work_point({
                        "vertical_grids": vg,
                        "horizontal_grids": hg,
                        "page_dimensions": {"width": page_w, "height": page_h},
                    })
                else:
                    work_point = None
            except Exception:
                work_point = None

        return {
            "members":         members,
            "grid_dimensions": grid_dimensions,
            "work_point":      work_point,
            "summary":         summary,
            "method":          method,
            "elapsed":         elapsed,
            "elapsed_seconds": elapsed,
            "count":           len(members),
            "grid_bubbles":    grid_bubbles,
            # Verified live against the real SteelGenie reference app
            # (2026-07-17 behavioral study, two separate projects): a
            # foundation-plan sheet asks for "Bottom of Column", not "Top
            # of Steel" -- different physical quantity (where a column
            # STARTS vs. where a floor's steel sits), same convention
            # CalSteel should match. _is_foundation_plan is already
            # computed above (same "FOUNDATION PLAN"/"FOUNDATION FRAMING"
            # text check that gates the foundation-outline symbol rules),
            # just not previously surfaced past this function. Purely
            # informational here -- frontend label + backend elevation
            # math both stay exactly as they are; see analyse.py for where
            # this gets persisted onto the page row.
            "is_foundation_plan": _is_foundation_plan,
            # These five were computed above for this page's own extraction
            # but never surfaced past this function -- app/workers/analyse.py
            # (the REAL persistence path behind /api/v1/pages/{page_id}/
            # analyse) needs exactly these to re-run
            # propagate_foundation_columns() with this sheet's actual grid/
            # page geometry. Without them, every caller downstream of this
            # dict falls back to empty grids and a hardcoded 1000x1000 "page
            # size" default, which silently breaks the foundation->framing
            # column propagation feature on every project, not just one --
            # points get compared against the wrong plan-bounds box and
            # almost all of them get rejected as "outside the sheet".
            "v_grid":      v_grid,
            "h_grid":      h_grid,
            "v_labels":    {round(x, 2): lbl for x, lbl in (v_labels or {}).items()},
            "h_labels":    {round(y, 2): lbl for y, lbl in (h_labels or {}).items()},
            "page_w":      page_w,
            "page_h":      page_h,
            "plan_bounds": list(plan_bounds) if plan_bounds else None,
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, str(e))


@app.get("/projects")
async def get_projects():
    if not supabase_client:
        raise HTTPException(503, "Supabase not configured")
    return supabase_client.table("projects").select("*, files(*)").execute().data


_SAVED_FILE = os.path.join(BASE_DIR, "saved_projects.json")


@app.post("/save-project")
async def save_project(req: SaveProjectRequest):
    import json as _json, uuid as _uuid

    projects: list = []
    if os.path.exists(_SAVED_FILE):
        try:
            with open(_SAVED_FILE, "r", encoding="utf-8") as f:
                projects = _json.load(f)
        except Exception:
            projects = []


    entry = {
        "id":           str(_uuid.uuid4()),
        "name":         req.name,
        "filename":     req.filename,
        "scale":        req.scale,
        "scale_ratio":  req.scale_ratio,
        "members":      req.members,
        "member_count": len(req.members),
        "page_count":   req.page_count,
        "created_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    projects.insert(0, entry)

    with open(_SAVED_FILE, "w", encoding="utf-8") as f:
        _json.dump(projects, f, ensure_ascii=False, indent=2)

    return {"status": "ok", "id": entry["id"]}


@app.get("/saved-projects")
async def get_saved_projects():
    import json as _json

    if not os.path.exists(_SAVED_FILE):
        return []
    try:
        with open(_SAVED_FILE, "r", encoding="utf-8") as f:
            projects = _json.load(f)
        return [
            {
                "id":           p.get("id"),
                "name":         p.get("name"),
                "filename":     p.get("filename", ""),
                "scale":        p.get("scale", ""),
                "member_count": p.get("member_count", 0),
                "page_count":   p.get("page_count", 1),
                "created_at":   p.get("created_at", ""),
            }
            for p in projects
        ]
    except Exception:
        return []


@app.post("/model")
async def build_model(req: ModelRequest):
    """
    Run full extraction and return a standardized structural model JSON.
    Always enables brace extraction regardless of the BRACE_EXTRACTION env flag.
    Response schema: { schema_version, source, page, floor_elevation_ft, units,
                       page_dims, nodes, members, connectivity, validation, gap_analysis }
    """
    from structural_schema import build_structural_model as _build_model

    # Run analysis with braces always on
    analysis_req = AnalysisRequest(
        filename         = req.filename,
        page_index       = req.page_index,
        scale_ratio      = req.scale_ratio,
        detect_braces    = True,
        detect_unlabeled = req.detect_unlabeled,
    )
    analysis = await analyse_pdf(analysis_req)
    members  = analysis["members"]

    # Get page dimensions (same logic as /analyse)
    tmp_path = os.path.join(UPLOAD_DIR, req.filename)
    ext      = os.path.splitext(req.filename)[1].lower()
    if ext in _IMAGE_EXTS:
        _pil = PILImage.open(tmp_path)
        page_w, page_h = float(_pil.width), float(_pil.height)
        _pil.close()
    else:
        _doc  = fitz.open(tmp_path)
        _page = _doc[req.page_index]
        if _page.rotation in (90, 270):
            page_w, page_h = _page.mediabox.width, _page.mediabox.height
        else:
            page_w, page_h = _page.rect.width, _page.rect.height
        _doc.close()

    # Fix 1: derive per-page floor elevation from page index when not explicit.
    # page_index=0 → floor at 1×FLOOR_HEIGHT_FT, base at 0
    # page_index=1 → floor at 2×FLOOR_HEIGHT_FT, base at 1×FLOOR_HEIGHT_FT
    if req.floor_elevation_ft is not None:
        floor_elev = req.floor_elevation_ft
        base_elev  = max(0.0, floor_elev - FLOOR_HEIGHT_FT)
    else:
        floor_elev = (req.page_index + 1) * FLOOR_HEIGHT_FT
        base_elev  = req.page_index * FLOOR_HEIGHT_FT

    print(f"[MODEL] page={req.page_index}  floor_elev={floor_elev}ft  base_elev={base_elev}ft")

    model = _build_model(
        members            = members,
        page_width_pts     = page_w,
        page_height_pts    = page_h,
        scale_ratio        = req.scale_ratio or 96,
        source             = req.filename,
        page               = req.page_index,
        floor_elevation_ft = floor_elev,
        base_elevation_ft  = base_elev,
    )

    model["analysis_summary"] = analysis.get("summary", {})
    model["analysis_method"]  = analysis.get("method", "unknown")
    model["elapsed"]          = analysis.get("elapsed", 0)
    return model


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
