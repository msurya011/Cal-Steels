"""
Brace Confidence Classifier — Universal Multi-Project Detector
---------------------------------------------------------------
Classifies diagonal line candidates into HIGH / MEDIUM / REJECT with five
layers of filtering, then enriches each accepted brace with structural metadata.

DETECTION LAYERS
----------------
  Layer 1 — Geometry
    HIGH      length 15–200 ft  AND  angle 20–70°  AND  not density-cluster
    MEDIUM    length  8–15 ft   AND  angle 20–70°  AND  not density-cluster
    REJECT    density-cluster / too-short / too-long

  Layer 2 — Hatch Boundary
    REJECT if ≥ HATCH_MIN_PARALLEL shorter parallel lines exist within the
    candidate's bounding box (corner-to-corner diagonal of a hatched region).

  Layer 3 — Detail Scale Protection
    For each candidate, find the nearest scale annotation on the page.
    If a local scale is found that is ≥ 2× larger than the page scale AND the
    candidate's length at that local scale is < MEDIUM_MIN_FT → REJECT as
    "detail_scale".

  Layer 4 — Drawing Context
    Classify each page as one of:
      braced_frame_elevation, framing_plan, roof_plan, foundation_plan,
      detail, schedule_legend, unknown

    Context effects:
      braced_frame_elevation → no change (highest trust)
      framing_plan           → no change
      roof_plan              → downgrade HIGH → MEDIUM (real braces kept visible)
      foundation_plan        → tag only, no confidence change
      detail                 → HARD REJECT all candidates
      schedule_legend        → HARD REJECT all candidates
      unknown                → no change

  Layer 5 — Structural Node Connectivity  (roof_plan + braced_frame_elevation)
    REJECT if neither endpoint lies within NODE_SNAP_PT of a structural node
    (H/V beam intersection or structural label centroid).

POST-CLASSIFICATION FILTERS
----------------------------
  annotation_xpair   — paired MEDIUM candidates forming a small mirror X
                        (section marker / north arrow) smaller than XPAIR_MIN_BAY_FT
  opening_annotation — candidate midpoint within OPENING_SNAP_PT of an OPENING
                        text label (stairwell / shaft diagonal graphic)

ENRICHMENT  (enrich_brace_results)
-----------------------------------
  config          : 'x_brace' | 'chevron' | 'single_diagonal'
                    Determined by geometric pairing of accepted candidates in the
                    same structural bay.
  section_label   : nearest HSS / W-shape / angle / TS callout text, or None
  role            : always 'lateral_unconfirmed' — estimator confirms seismic role
                    (never auto-assign; per SteelGenie parity plan §5.3 Layer 3)
  detection_method: 'rules' (vision_fallback wired in future Gemini integration)

OUTPUT
------
  • Console table per PDF + per page
  • JSON: brace_classifier_results.json  (per-page counts + context labels)
  • Per-page PNG overlays: HIGH=green  MEDIUM=amber  REJECT=grey

USAGE
-----
  python brace_classifier.py               # all PDFs in uploads/
  python brace_classifier.py --pages       # also print per-page detail
"""
import os, sys, re, math, json, argparse
import fitz
from PIL import Image, ImageDraw, ImageFont
from collections import defaultdict

HERE       = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(HERE, "uploads")
OUT_DIR    = os.path.join(HERE, "brace_classifier_output")
os.makedirs(OUT_DIR, exist_ok=True)

# ── Tunable thresholds ────────────────────────────────────────────────────────
ANGLE_MIN          = 20.0   # degrees from horizontal
ANGLE_MAX          = 70.0
HIGH_MIN_FT        = 15.0
MEDIUM_MIN_FT      =  8.0
MAX_LENGTH_FT      = 200.0  # reject impossibly long lines (building boundaries, etc.)
DENSITY_BIN_FT     =  1.0   # bucket width for cluster detection
DENSITY_THRESHOLD  =  8     # candidates per bucket → cluster
HATCH_MIN_PARALLEL =  6     # min parallel shorter lines within bbox -> hatch boundary
DETAIL_SCALE_RATIO =  2.0   # local scale must be >= this x page scale to trigger
SCALE_SEARCH_DIST  = 400.0  # pts radius to search for a local scale annotation
DEDUP_PT           = 15.0   # per-endpoint pt tolerance for second-pass proximity dedup
                             # catches BIM-export pattern: same brace in two PDF path
                             # objects with ~6-12 pt endpoint jitter (measured max: 12.5 pt)

# Context hard-reject: pages of these types cannot contain structural braces
HARD_REJECT_CONTEXTS = {"detail", "schedule_legend"}

# ── Layer 5 — Structural Node Connectivity ────────────────────────────────────
# A true structural brace must terminate at a structural node (beam/column
# intersection).  Annotation symbols, slope arrows, and detail graphics have
# no structural connection point at either end.
#
# NODE_SNAP_PT     : radius (pts) within which an endpoint is "on" a node
# NODE_MIN_LINE_FT : minimum line length (structural feet) for a line to
#                    contribute to the node grid.  This keeps primary structural
#                    beams and removes sub-framing / joist connections whose
#                    dense intersection matrix would make every diagonal look
#                    connected.
NODE_SNAP_PT      = 25.0   # pt radius
NODE_MIN_LINE_FT  =  6.0   # structural feet — primary beam minimum span

# Minimum structural bay span for a real X-brace (both axes).
# An annotation X-pair (section marker, north arrow, detail callout) that forms
# a small mirror crossing is rejected if its bounding box is smaller than this
# in BOTH dimensions.  Real structural X-bracing always spans at least one full
# structural bay — typically ≥ 15 ft.  8 ft is a very conservative lower bound.
XPAIR_MIN_BAY_FT  =  8.0
OPENING_SNAP_PT   = 150.0  # pt radius: diagonal inside an OPENING annotation is not a brace

# Contexts where node connectivity is checked.
# roof_plan only: false positive rate is highest here (slope arrows, joist web
# patterns, hatch boundary diagonals) and real structural roof bracing is rare
# and always clearly connected to the primary column/beam grid.
# framing_plan / elevation / foundation_plan excluded: real brace endpoints
# sometimes fall at beam stubs or column symbols that produce no H/V
# intersection node, causing false negatives.  Separate per-context work needed.
# Contexts where node connectivity is checked (Layer 5).
# framing_plan uses a STRICT BOTH-endpoint check (both ends must be on nodes).
# roof_plan / braced_frame_elevation use a lenient EITHER-endpoint check.
# The distinction matters because on a framing plan the beam grid is so dense
# that annotation diagonals often land near ONE node by accident — but a real
# structural brace always connects TWO distinct structural points.
NODE_CHECK_CONTEXTS      = {"roof_plan", "braced_frame_elevation", "framing_plan"}
NODE_STRICT_BOTH_CONTEXTS = {"framing_plan"}   # require both endpoints on nodes

_STRUCT_LABEL_RE = re.compile(
    r'\b(COL\b|HSS\d|W\d{1,2}[Xx]|TS\d|MC\d|BF\s*[-–]\s*\d)',
    re.I)
_OPENING_REGION_RE = re.compile(r'\bOPENING\b', re.I)

# ── Brace enrichment constants ────────────────────────────────────────────────
# Maximum distance (pts) from brace midpoint to associate a section callout.
SECTION_SNAP_PT   = 300.0
# Endpoint proximity (pts) to decide two braces share a connection point
# (chevron / K-brace).  Larger than NODE_SNAP_PT to account for imprecise
# CAD endpoints near the convergence point.
CHEVRON_SNAP_PT   =  60.0

# Structural section callout patterns — HSS, W-shapes, angles, tube steel etc.
# Matches the designation text label nearest each accepted brace.
_SECTION_RE = re.compile(
    r'\b(?:'
    r'HSS\s*\d+(?:[xX×][\d/]+){1,3}'    # HSS12X8X3/8, HSS6X6X3/8
    r'|W\s*\d{1,3}[xX×]\d+(?:\.\d+)?'   # W24X94, W16X26
    r'|WT\s*[\d.]+[xX×][\d.]+'           # WT5X6.5
    r'|2?L\s*\d+(?:[xX×][\d/]+){1,3}'   # L4X4X1/2, 2L5X5X3/8
    r'|TS\s*\d+(?:[xX×][\d/]+){1,3}'    # TS4X4X3/16
    r'|MC\s*[\d.]+[xX×][\d.]+'           # MC12X10.6
    r')',
    re.I
)

# ── PDFs to scan ──────────────────────────────────────────────────────────────
SCAN_PDFS = [
    ("#Structural binder.pdf",                               64.0),
    ("Structural snaps.pdf",                                 96.0),
    ("07_STRUCTURAL_COMBINED.pdf",                          192.0),
    ("Latest_Structural dwg_Binder (Addendum-02).pdf",       96.0),
    ("04_-_STRUCTURAL.pdf",                                  96.0),
    ("2026.03.27_Bayhealth Sussex MOB_DD Set_Structural.pdf",192.0),
    ("NCU SherMan_Structural.pdf",                           96.0),
    ("STRUCTURAL 5-26-26.pdf",                               96.0),
    ("Pages from 2026.05.08_FF Martha Washington Building - Issued for Pricing.pdf", 96.0),
    ("02 Struct 98 Spruce_2026-03-13_BID.pdf",               96.0),
]


def scale_to_pts_per_foot(scale_ratio: float) -> float:
    return 864.0 / scale_ratio if scale_ratio > 0 else 9.0


def _dedup_proximity(segments: list) -> list:
    """
    Second-pass dedup: remove segments that are geometrically near an
    already-kept longer segment.

    Catches the BIM-export pattern where the same structural brace is encoded
    as two separate PDF path objects (different drawing_idx) with consistent
    endpoint jitter of 6-12 pt.  The first-pass key-based dedup uses a 1-pt
    bin and cannot catch this.

    Algorithm: sort longest-first (keep the authoritative member); for each
    candidate check if the sum of both endpoint distances to any kept segment
    is < DEDUP_PT * 2 (forward or reversed).  If so, suppress the candidate.

    Safety: genuinely adjacent braces share at most ONE near endpoint (the
    shared column joint); their far endpoints are a full bay width apart,
    making the total endpoint-pair distance >> DEDUP_PT * 2.
    """
    segs = sorted(segments, key=lambda s: s["length_ft"], reverse=True)
    kept = []
    for s in segs:
        is_dup = False
        for k in kept:
            dfwd = (math.hypot(s["x1"] - k["x1"], s["y1"] - k["y1"]) +
                    math.hypot(s["x2"] - k["x2"], s["y2"] - k["y2"]))
            drev = (math.hypot(s["x1"] - k["x2"], s["y1"] - k["y2"]) +
                    math.hypot(s["x2"] - k["x1"], s["y2"] - k["y1"]))
            if min(dfwd, drev) < DEDUP_PT * 2:
                is_dup = True
                break
        if not is_dup:
            kept.append(s)
    return kept


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 1 — Geometry extraction + density cluster
# ══════════════════════════════════════════════════════════════════════════════

def extract_diagonals(page, ppf: float) -> list:
    """
    Return every solid, non-dashed diagonal (20–70°) line segment ≥ 3 ft on
    the page.  No upper length limit here — filters applied in classify().
    """
    min_pt   = 3.0 * ppf
    results  = []
    seen     = set()

    try:
        for d in page.get_drawings():
            dashes = str(d.get("dashes") or "").strip()
            da = re.match(r'\[([^\]]*)\]', dashes)
            if da and da.group(1).strip():
                continue

            sw = float(d.get("width") or 0)

            for item in d.get("items", []):
                if item[0] != "l":
                    continue
                try:
                    p1, p2 = item[1], item[2]
                    dx, dy = p2.x - p1.x, p2.y - p1.y
                    ln     = math.hypot(dx, dy)
                    if ln < min_pt:
                        continue

                    ang   = abs(math.degrees(math.atan2(dy, dx))) % 180
                    ang_h = min(ang, 180 - ang)
                    if not (ANGLE_MIN <= ang_h <= ANGLE_MAX):
                        continue

                    key  = (round(p1.x), round(p1.y), round(p2.x), round(p2.y))
                    rkey = (round(p2.x), round(p2.y), round(p1.x), round(p1.y))
                    if key in seen or rkey in seen:
                        continue
                    seen.add(key)

                    results.append({
                        "x1":          p1.x,
                        "y1":          p1.y,
                        "x2":          p2.x,
                        "y2":          p2.y,
                        "length_ft":   round(ln / ppf, 2),
                        "angle_from_h":round(ang_h, 1),
                        "stroke_w":    round(sw, 2),
                    })
                except Exception:
                    continue
    except Exception:
        pass
    return _dedup_proximity(results)


def find_density_clusters(candidates: list) -> set:
    """
    Bin candidates by floor(length_ft / DENSITY_BIN_FT).
    Return indices whose bin has ≥ DENSITY_THRESHOLD members.
    """
    bins: dict[int, list] = defaultdict(list)
    for i, c in enumerate(candidates):
        b = int(c["length_ft"] / DENSITY_BIN_FT)
        bins[b].append(i)

    cluster = set()
    for idx_list in bins.values():
        if len(idx_list) >= DENSITY_THRESHOLD:
            cluster.update(idx_list)
    return cluster


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 2 — Hatch boundary detection
# ══════════════════════════════════════════════════════════════════════════════

def is_hatch_boundary(candidate: dict, all_diagonals: list) -> bool:
    """
    Returns True if the candidate is the corner-to-corner diagonal of a
    hatched fill region.

    Detects: ≥ HATCH_MIN_PARALLEL lines that are (a) at the same angle ±5°,
    (b) shorter than the candidate, and (c) have their midpoint inside the
    candidate's bounding box.
    """
    c_ang = candidate["angle_from_h"]
    c_len = candidate["length_ft"]
    bx0   = min(candidate["x1"], candidate["x2"])
    by0   = min(candidate["y1"], candidate["y2"])
    bx1   = max(candidate["x1"], candidate["x2"])
    by1   = max(candidate["y1"], candidate["y2"])
    pad   = 20.0

    count = 0
    for line in all_diagonals:
        if line is candidate:
            continue
        if abs(line["angle_from_h"] - c_ang) > 5.0:
            continue
        if line["length_ft"] >= c_len * 0.95:
            continue
        mx = (line["x1"] + line["x2"]) / 2
        my = (line["y1"] + line["y2"]) / 2
        if (bx0 - pad <= mx <= bx1 + pad and
                by0 - pad <= my <= by1 + pad):
            count += 1
            if count >= HATCH_MIN_PARALLEL:
                return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 3 — Detail scale protection
# ══════════════════════════════════════════════════════════════════════════════

# Regex: N/D" = 1'-0"  or  N" = 1'-0"  (architectural scale annotations)
_SCALE_FRAC = re.compile(
    r'(\d{1,3})\s*/\s*(\d{1,3})\s*["\']?\s*=\s*1\s*[-\']',
    re.I)
_SCALE_INT  = re.compile(
    r'(\d{1,2}(?:\.\d)?)\s*["\']?\s*=\s*1\s*[-\']',
    re.I)


def find_scale_annotations(page) -> list:
    """
    Parse every text span on the page for architectural scale annotations.
    Returns list of (ppf_at_this_scale, x, y).

    Formula:  ppf = 72 × (N/D)  for "N/D" = 1'" pattern
              ppf = 72 × N       for "N" = 1'" pattern
    (72 pts/inch on-screen; N/D inches on drawing = 1 foot in reality)
    """
    annotations = []
    try:
        td = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    except Exception:
        return annotations

    for block in td.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span.get("text", "").strip()
                if not t or "=" not in t:
                    continue
                ox = span.get("origin", (0, 0))[0]
                oy = span.get("origin", (0, 0))[1]

                m = _SCALE_FRAC.search(t)
                if m:
                    num, den = int(m.group(1)), int(m.group(2))
                    if num > 0 and den > 0:
                        ppf = 72.0 * num / den
                        annotations.append((ppf, ox, oy))
                    continue

                m = _SCALE_INT.search(t)
                if m:
                    n = float(m.group(1))
                    if 0 < n <= 12:   # sanity: 1"=1' to 12"=1'
                        ppf = 72.0 * n
                        annotations.append((ppf, ox, oy))

    # Deduplicate by rounding ppf to 1 decimal
    seen_ppf = set()
    unique = []
    for (ppf, x, y) in annotations:
        key = round(ppf, 1)
        if key not in seen_ppf:
            seen_ppf.add(key)
            unique.append((ppf, x, y))
    return unique


def _nearest_scale(candidate: dict, scale_annotations: list, page_ppf: float):
    """
    Return the (local_ppf, dist_pts) of the nearest scale annotation within
    SCALE_SEARCH_DIST that has ppf > page_ppf * DETAIL_SCALE_RATIO.
    Returns (None, None) if nothing qualifies.
    """
    mx = (candidate["x1"] + candidate["x2"]) / 2
    my = (candidate["y1"] + candidate["y2"]) / 2

    best_ppf  = None
    best_dist = float("inf")
    for (ann_ppf, ax, ay) in scale_annotations:
        if ann_ppf < page_ppf * DETAIL_SCALE_RATIO:
            continue          # not a larger-scale detail
        dist = math.hypot(mx - ax, my - ay)
        if dist < best_dist and dist <= SCALE_SEARCH_DIST:
            best_dist = dist
            best_ppf  = ann_ppf

    return (best_ppf, best_dist) if best_ppf is not None else (None, None)


def check_detail_scale(candidate: dict, scale_annotations: list,
                       page_ppf: float) -> tuple:
    """
    Returns (is_mismatch: bool, reason: str|None).

    If a nearby detail annotation implies a much larger scale, re-compute the
    candidate's length at the local scale.  If that real length < MEDIUM_MIN_FT
    the candidate is a scale-mismatch false positive.
    """
    local_ppf, _ = _nearest_scale(candidate, scale_annotations, page_ppf)
    if local_ppf is None:
        return False, None

    real_ft = candidate["length_ft"] * page_ppf / local_ppf
    if real_ft < MEDIUM_MIN_FT:
        return True, f"detail_scale({local_ppf:.1f}pt/ft→{real_ft:.1f}ft)"
    return False, None


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 4 — Drawing context classification
# ══════════════════════════════════════════════════════════════════════════════

# (pattern, weight) pairs per context type
_CTX_PATTERNS: dict[str, list] = {
    "braced_frame_elevation": [
        (re.compile(r'BRACED\s+FRAME\s+ELEVATION', re.I), 3),  # must say ELEVATION
        (re.compile(r'BRAC(?:ED|ING)\s+(?:FRAME\s+)?ELEVATION', re.I), 3),
        (re.compile(r'\bBF\s*[-–]\s*\d+\b', re.I), 1),         # reduced: plan refs use BF labels too
        (re.compile(r'BRACING\s+ELEVATION', re.I), 3),
        (re.compile(r'LATERAL\s+FRAME\s+ELEVATION', re.I), 3),
    ],
    "framing_plan": [
        (re.compile(r'FRAMING\s+PLAN', re.I), 3),
        (re.compile(r'LEVEL\s+\d+\s+FRAMING', re.I), 3),
        (re.compile(r'STRUCTURAL\s+(?:FLOOR\s+)?PLAN', re.I), 2),
        (re.compile(r'PARTIAL\s+FRAMING\s+PLAN', re.I), 3),
        (re.compile(r'FLOOR\s+PLAN(?!\s+OVERALL)', re.I), 2),
    ],
    "roof_plan": [
        (re.compile(r'ROOF\s+FRAMING\s+PLAN', re.I), 3),
        (re.compile(r'ROOF\s+PLAN', re.I), 3),
        (re.compile(r'ROOF\s+DECK\s+PLAN', re.I), 3),
        (re.compile(r'(?:HIGH|LOW|OVERALL)\s+ROOF', re.I), 3),
        (re.compile(r'CANOPY\s+(?:FRAMING\s+)?PLAN', re.I), 2),
        (re.compile(r'ROOF\s+JOIST', re.I), 2),
    ],
    "foundation_plan": [
        (re.compile(r'FOUNDATION\s+PLAN', re.I), 3),
        (re.compile(r'MAT\s+FOUNDATION', re.I), 2),
        (re.compile(r'FOOTING\s+PLAN', re.I), 3),
        (re.compile(r'PILE\s+(?:LAYOUT\s+)?PLAN', re.I), 2),
        (re.compile(r'GRADE\s+BEAM\s+PLAN', re.I), 2),
    ],
    "detail": [
        (re.compile(r'JOIST\s+POINT\s+LOAD\s+DIAGRAM', re.I), 4),
        (re.compile(r'PARTIAL\s+(?:ROOF\s+)?JOIST', re.I), 3),
        (re.compile(r'CONNECTION\s+DETAIL', re.I), 2),
        (re.compile(r'STUD\s+WALL\s+DETAIL', re.I), 2),
        (re.compile(r'NOT\s+TO\s+SCALE\b|\bNTS\b', re.I), 2),
        (re.compile(r'SECTION\s+[A-Z]-[A-Z]', re.I), 2),
        (re.compile(r'WELD\s+SCHEDULE|BOLT\s+SCHEDULE', re.I), 2),
    ],
    "schedule_legend": [
        (re.compile(r'\bSCHEDULE\b', re.I), 2),
        (re.compile(r'\bLEGEND\b', re.I), 2),
        (re.compile(r'GENERAL\s+NOTES', re.I), 2),
        (re.compile(r'\bKEYNOTES\b', re.I), 2),
        (re.compile(r'ABBREVIATION', re.I), 2),
        (re.compile(r'TYPICAL\s+NOTES', re.I), 2),
        (re.compile(r'TYPICAL\s+BRAC(?:ED?|ING)\s+FRAME', re.I), 4),
        (re.compile(r'FOR\s+TYPICAL\s+BRAC', re.I), 4),
    ],
}

# Confidence modifier per context type
CONTEXT_MODIFIER = {
    "braced_frame_elevation": +1,   # upgrade: MEDIUM→HIGH if length qualifies
    "framing_plan":            0,
    "roof_plan":              -1,   # downgrade: HIGH→MEDIUM
    "foundation_plan":         0,   # tag only
    "detail":                 -99,  # HARD REJECT
    "schedule_legend":        -99,  # HARD REJECT
    "unknown":                 0,
}


def classify_page_context(page) -> tuple:
    """
    Classify page type by scanning both the drawing body and the title block.
    Returns (context_type: str, score: int).

    Drawing titles live in the title block (bottom ~15% of sheet) and are often
    beyond a 3000-char body truncation.  We scan the bottom strip separately so
    that 'LEVEL 2 FRAMING PLAN – AREA B' always outweighs stray BF-X callouts
    that appear in the drawing body.
    """
    try:
        r = page.rect
        full_text  = page.get_text("text")
        body_text  = full_text[:2500]
        # PDF stream order often places title-block objects after the drawing body,
        # so the title appears near the END of the extracted text regardless of its
        # visual position on the sheet.  Scanning the tail catches "SECOND FLOOR
        # FRAMING PLAN" and similar titles that body_text[:2500] misses.
        tail_text  = full_text[-2000:] if len(full_text) > 4500 else ""
        # Physical bottom-15 % clip for traditional bottom-right title blocks
        title_clip = fitz.Rect(r.x0, r.y1 * 0.85, r.x1, r.y1)
        clip_text  = page.get_text("text", clip=title_clip)
        text = body_text + "\n" + tail_text + "\n" + clip_text
    except Exception:
        return "unknown", 0

    scores: dict[str, int] = defaultdict(int)
    for ctx_type, patterns in _CTX_PATTERNS.items():
        for pat, weight in patterns:
            if pat.search(text):
                scores[ctx_type] += weight

    # Deduct from braced_frame_elevation if there is strong plan-view evidence
    if scores.get("framing_plan", 0) >= 2 or scores.get("roof_plan", 0) >= 2 or scores.get("foundation_plan", 0) >= 2:
        scores["braced_frame_elevation"] -= 5

    # Deduct from schedule_legend and detail if braced_frame_elevation is strong
    if scores.get("braced_frame_elevation", 0) >= 3:
        scores["schedule_legend"] -= 10
        scores["detail"] -= 10

    if not scores:
        return "unknown", 0

    # ── Multi-frame brace schedule detection ─────────────────────────────────
    # A schedule page lists every BF-X type (BF-1, BF-2, BF-3 …) as its primary
    # content.  A normal framing plan may also reference multiple BF-X callouts,
    # so only fire schedule detection when framing_plan hasn't scored strongly
    # (framing_plan score < 3 means no clear 'FRAMING PLAN' title was found).
    _BF_LABEL_RE = re.compile(r'BF\s*[-–]\s*\d+', re.I)
    unique_bf_labels = set(m.group().upper().replace(' ', '').replace('–', '-')
                           for m in _BF_LABEL_RE.finditer(text))
    if len(unique_bf_labels) >= 3 and scores.get("framing_plan", 0) < 3 and scores.get("braced_frame_elevation", 0) < 3:
        return "schedule_legend", 99

    # Resolve ties: elevation > framing_plan > roof_plan > others
    priority = ["braced_frame_elevation", "framing_plan", "roof_plan",
                "foundation_plan", "detail", "schedule_legend"]
    best_score = max(scores.values())
    best_types = [t for t in priority if scores.get(t, 0) == best_score]
    return best_types[0], best_score


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 5 — Structural node connectivity
# ══════════════════════════════════════════════════════════════════════════════

def extract_structural_nodes(page, ppf: float = 9.0) -> list:
    """
    Return (x, y, node_type) structural node candidates for the page.
    node_type is 'hv' (H/V beam intersection) or 'label' (structural label centroid).

    Source 1 — Grid intersections ('hv'):
      Collect every near-horizontal (±10°) and near-vertical (±10°) line that
      is at least NODE_MIN_LINE_FT long.  Compute pairwise intersections and
      keep those that lie within NODE_SNAP_PT of both segments.
      Using only LONG lines (primary structural members) prevents the dense
      sub-framing / joist intersection matrix from creating spurious nodes.

    Source 2 — Structural label centroids ('label'):
      Text spans whose content matches COL, HSS, W-shape, BF-X, etc.
      Used to anchor brace endpoints that fall at column symbols rather than
      beam-beam crossings.
    """
    min_pt = NODE_MIN_LINE_FT * ppf       # minimum line length in page-points
    h_segs: list = []
    v_segs: list = []

    try:
        for d in page.get_drawings():
            for item in d.get("items", []):
                if item[0] != "l":
                    continue
                p1, p2 = item[1], item[2]
                dx, dy = p2.x - p1.x, p2.y - p1.y
                ln     = math.hypot(dx, dy)
                if ln < min_pt:
                    continue
                ang   = abs(math.degrees(math.atan2(dy, dx))) % 180
                ang_h = min(ang, 180 - ang)
                if ang_h <= 10:
                    h_segs.append((p1.x, p1.y, p2.x, p2.y))
                elif ang_h >= 80:
                    v_segs.append((p1.x, p1.y, p2.x, p2.y))
    except Exception:
        pass

    nodes: list = []
    snap = NODE_SNAP_PT

    for (hx1, hy1, hx2, hy2) in h_segs:
        for (vx1, vy1, vx2, vy2) in v_segs:
            hxd = hx2 - hx1;  hyd = hy2 - hy1
            vxd = vx2 - vx1;  vyd = vy2 - vy1
            denom = hxd * vyd - hyd * vxd
            if abs(denom) < 1e-6:
                continue
            dx0 = vx1 - hx1;  dy0 = vy1 - hy1
            t = (dx0 * vyd - dy0 * vxd) / denom
            s = (dx0 * hyd - dy0 * hxd) / denom
            hlen = math.hypot(hxd, hyd)
            vlen = math.hypot(vxd, vyd)
            if hlen < 1 or vlen < 1:
                continue
            tol_t = snap / hlen
            tol_s = snap / vlen
            if (-tol_t <= t <= 1 + tol_t) and (-tol_s <= s <= 1 + tol_s):
                nodes.append((hx1 + t * hxd, hy1 + t * hyd, 'hv'))

    # Structural text label centroids (COL, HSS, BF-X, W-shapes)
    # Used on roof_plan pages where column labels mark real structural positions.
    try:
        td = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        for block in td.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span.get("text", "").strip()
                    if _STRUCT_LABEL_RE.search(t):
                        ox = span.get("origin", (0, 0))[0]
                        oy = span.get("origin", (0, 0))[1]
                        nodes.append((ox, oy, 'label'))
    except Exception:
        pass

    # Deduplicate: merge nodes within NODE_SNAP_PT of each other
    merged: list = []
    for (nx, ny, nt) in nodes:
        if not any(math.hypot(nx - mx, ny - my) < snap for (mx, my, _) in merged):
            merged.append((nx, ny, nt))
    return merged


def _endpoints_on_nodes(cand: dict, nodes: list) -> tuple:
    """
    Return (p1_any, p2_any, p1_hv, p2_hv):
      p1/p2_any — endpoint within NODE_SNAP_PT of any node (hv or label)
      p1/p2_hv  — endpoint within NODE_SNAP_PT of an H/V intersection node only
    """
    p1_any = any(math.hypot(cand["x1"] - nx, cand["y1"] - ny) < NODE_SNAP_PT
                 for nx, ny, _ in nodes)
    p2_any = any(math.hypot(cand["x2"] - nx, cand["y2"] - ny) < NODE_SNAP_PT
                 for nx, ny, _ in nodes)
    p1_hv  = any(math.hypot(cand["x1"] - nx, cand["y1"] - ny) < NODE_SNAP_PT
                 for nx, ny, nt in nodes if nt == 'hv')
    p2_hv  = any(math.hypot(cand["x2"] - nx, cand["y2"] - ny) < NODE_SNAP_PT
                 for nx, ny, nt in nodes if nt == 'hv')
    return p1_any, p2_any, p1_hv, p2_hv


def extract_opening_regions(page) -> list:
    """
    Return (cx, cy) of every 'OPENING' / 'OPEN' text block on the page.

    In framing plans, floor openings (stairwells, elevator shafts, mechanical
    penetrations) are conventionally marked with diagonal X-lines drawn across
    the void.  These lines must not be classified as structural braces.
    Any diagonal whose midpoint falls within OPENING_SNAP_PT of an OPENING
    label is rejected by the classifier.
    """
    out = []
    for b in page.get_text("blocks"):
        if _OPENING_REGION_RE.search(b[4]):
            out.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  BRACE ENRICHMENT — config classification + section label attachment
# ══════════════════════════════════════════════════════════════════════════════

def _lines_cross(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2) -> bool:
    """Return True if segment A and segment B properly intersect (cross each other)."""
    def _cross2d(ux, uy, vx, vy):
        return ux * vy - uy * vx

    d1x, d1y = ax2 - ax1, ay2 - ay1
    d2x, d2y = bx2 - bx1, by2 - by1
    denom = _cross2d(d1x, d1y, d2x, d2y)
    if abs(denom) < 1e-9:
        return False  # parallel or collinear

    dx, dy = bx1 - ax1, by1 - ay1
    t = _cross2d(dx, dy, d2x, d2y) / denom
    u = _cross2d(dx, dy, d1x, d1y) / denom
    # Strict interior intersection (avoids counting endpoint-touches)
    return 0.05 < t < 0.95 and 0.05 < u < 0.95


def _bboxes_overlap(a: dict, b: dict, tol: float = 50.0) -> bool:
    """Return True if the bounding boxes of two candidates overlap (same bay)."""
    ax0, ax1 = min(a["x1"], a["x2"]), max(a["x1"], a["x2"])
    ay0, ay1 = min(a["y1"], a["y2"]), max(a["y1"], a["y2"])
    bx0, bx1 = min(b["x1"], b["x2"]), max(b["x1"], b["x2"])
    by0, by1 = min(b["y1"], b["y2"]), max(b["y1"], b["y2"])
    return not (ax1 + tol < bx0 or bx1 + tol < ax0 or
                ay1 + tol < by0 or by1 + tol < ay0)


def _share_endpoint(a: dict, b: dict, snap: float = CHEVRON_SNAP_PT) -> bool:
    """Return True if any endpoint of A is within snap of any endpoint of B."""
    for ax, ay in ((a["x1"], a["y1"]), (a["x2"], a["y2"])):
        for bx, by in ((b["x1"], b["y1"]), (b["x2"], b["y2"])):
            if math.hypot(ax - bx, ay - by) < snap:
                return True
    return False


def _classify_configs(results: list) -> None:
    """
    Mutate accepted candidates in-place, adding 'config' field:
      'x_brace'        — two braces in same bay whose line segments cross
      'chevron'        — two braces that share a common endpoint (V/chevron/K)
      'single_diagonal'— no partner found in the same bay
    Priority: x_brace > chevron > single_diagonal.
    """
    _PRIORITY = {"x_brace": 3, "chevron": 2, "single_diagonal": 1}

    def _upgrade(cfg_map, idx, new):
        if _PRIORITY.get(new, 0) > _PRIORITY.get(cfg_map.get(idx, "single_diagonal"), 0):
            cfg_map[idx] = new

    accepted_idx = [i for i, c in enumerate(results)
                    if c.get("confidence") in ("HIGH", "MEDIUM")]
    cfg_map: dict[int, str] = {}

    for ii, i in enumerate(accepted_idx):
        a = results[i]
        for jj in range(ii + 1, len(accepted_idx)):
            j = accepted_idx[jj]
            b = results[j]

            if not _bboxes_overlap(a, b):
                continue

            if _lines_cross(a["x1"], a["y1"], a["x2"], a["y2"],
                            b["x1"], b["y1"], b["x2"], b["y2"]):
                _upgrade(cfg_map, i, "x_brace")
                _upgrade(cfg_map, j, "x_brace")
            elif _share_endpoint(a, b):
                _upgrade(cfg_map, i, "chevron")
                _upgrade(cfg_map, j, "chevron")

    for i, c in enumerate(results):
        if c.get("confidence") in ("HIGH", "MEDIUM"):
            c["config"] = cfg_map.get(i, "single_diagonal")
        else:
            c["config"] = None


def _attach_section_labels(results: list, page) -> None:
    """
    Mutate accepted candidates in-place, adding 'section_label' field.
    Finds the nearest structural section callout (HSS, W-shape, angle, etc.)
    within SECTION_SNAP_PT of each brace midpoint.
    """
    blocks = page.get_text("blocks")
    # Pre-filter to blocks that contain a section callout
    labeled_blocks = []
    for b in blocks:
        m = _SECTION_RE.search(b[4])
        if m:
            bx = (b[0] + b[2]) / 2
            by = (b[1] + b[3]) / 2
            # Normalise: collapse spaces, uppercase
            label = re.sub(r'\s+', '', m.group()).upper()
            labeled_blocks.append((bx, by, label))

    for c in results:
        if c.get("confidence") not in ("HIGH", "MEDIUM"):
            c["section_label"] = None
            continue
        cx = (c["x1"] + c["x2"]) / 2
        cy = (c["y1"] + c["y2"]) / 2
        best_label = None
        best_dist  = float("inf")
        for bx, by, label in labeled_blocks:
            d = math.hypot(cx - bx, cy - by)
            if d < best_dist:
                best_dist  = d
                best_label = label
        c["section_label"] = best_label if best_dist < SECTION_SNAP_PT else None


def enrich_brace_results(results: list, page) -> list:
    """
    Post-classify enrichment — call immediately after classify().

    Adds these fields to every result entry:
      config           : 'x_brace' | 'chevron' | 'single_diagonal' | None (rejected)
      section_label    : nearest structural section callout text, or None
      role             : 'lateral_unconfirmed' — never auto-assign seismic role;
                         surface to estimator for confirmation (per MD §5.3 Layer 3)
      detection_method : 'rules' — 'vision_fallback' when Gemini path is wired

    Mutates and returns the same list for convenience.
    """
    _classify_configs(results)
    _attach_section_labels(results, page)
    for c in results:
        c.setdefault("role",             "lateral_unconfirmed")
        c.setdefault("detection_method", "rules")
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  CLASSIFY — combine all five layers
# ══════════════════════════════════════════════════════════════════════════════

def classify(candidates: list,
             page_context: str = "unknown",
             scale_annotations: list = None,
             ppf: float = 9.0,
             structural_nodes: list = None,
             opening_regions: list = None) -> list:
    """
    Apply five-layer classification to every candidate.

    Parameters
    ----------
    candidates        : output of extract_diagonals()
    page_context      : output of classify_page_context()[0]
    scale_annotations : output of find_scale_annotations()
    ppf               : pts-per-foot for this page
    structural_nodes  : output of extract_structural_nodes() — optional.
                        When provided, Layer 5 rejects candidates on
                        framing_plan / roof_plan / foundation_plan pages
                        whose endpoints land on no structural node.
    opening_regions   : output of extract_opening_regions() — optional.
                        When provided, rejects any candidate whose midpoint
                        lies within OPENING_SNAP_PT of an OPENING text label.

    Added keys per candidate:
      confidence    : "HIGH" | "MEDIUM" | "REJECT"
      reject_reason : str | None
      page_context  : str (propagated metadata)
    """
    cluster_set = find_density_clusters(candidates)
    modifier    = CONTEXT_MODIFIER.get(page_context, 0)
    results     = []

    for i, c in enumerate(candidates):
        c = dict(c)
        c["page_context"] = page_context

        # ── Layer 1: geometry ────────────────────────────────────────────────
        if i in cluster_set:
            c["confidence"]    = "REJECT"
            c["reject_reason"] = "density_cluster"
            results.append(c)
            continue

        if c["length_ft"] < MEDIUM_MIN_FT:
            c["confidence"]    = "REJECT"
            c["reject_reason"] = "too_short"
            results.append(c)
            continue

        if c["length_ft"] > MAX_LENGTH_FT:
            c["confidence"]    = "REJECT"
            c["reject_reason"] = "too_long"
            results.append(c)
            continue

        # ── Layer 4 (context) hard-reject: check before geometry work ────────
        if modifier <= -99:
            c["confidence"]    = "REJECT"
            c["reject_reason"] = f"context:{page_context}"
            results.append(c)
            continue

        # Base confidence from length
        base = "HIGH" if c["length_ft"] >= HIGH_MIN_FT else "MEDIUM"

        # ── Layer 2: hatch boundary ──────────────────────────────────────────
        if is_hatch_boundary(c, candidates):
            c["confidence"]    = "REJECT"
            c["reject_reason"] = "hatch_boundary"
            results.append(c)
            continue

        # ── Layer 3: detail scale mismatch ───────────────────────────────────
        if scale_annotations:
            is_mm, mm_reason = check_detail_scale(c, scale_annotations, ppf)
            if is_mm:
                c["confidence"]    = "REJECT"
                c["reject_reason"] = mm_reason
                results.append(c)
                continue

        # ── Layer 4: context modifier (soft adjustment) ───────────────────────
        if modifier < 0 and base == "HIGH":
            base = "MEDIUM"
            c["reject_reason"] = None
        elif modifier > 0 and base == "MEDIUM" and c["length_ft"] >= HIGH_MIN_FT:
            base = "HIGH"
            c["reject_reason"] = None
        else:
            c["reject_reason"] = None

        # ── Layer 5: structural node connectivity ─────────────────────────────
        # A valid brace must terminate at structural nodes (beam/column grid).
        # Annotation diagonals (stair symbols, section markers, slope arrows)
        # do not connect two distinct structural points.
        #
        # Strictness by context:
        #   framing_plan          → BOTH endpoints must be on a node.
        #     Dense beam grid means one endpoint can accidentally land near a
        #     grid intersection.  A real brace always spans two structural pts.
        #   roof_plan / elevation → EITHER endpoint must be on a node.
        #     Sparser grid; single-endpoint confirmation is sufficient.
        #   braced_frame_elevation, unknown → no check (context is itself
        #     a strong signal that diagonals are structural).
        if structural_nodes is not None and page_context in NODE_CHECK_CONTEXTS:
            p1_any, p2_any, p1_hv, p2_hv = _endpoints_on_nodes(c, structural_nodes)
            if page_context in NODE_STRICT_BOTH_CONTEXTS:
                # STRICT: both endpoints required
                if not p1_any or not p2_any:
                    c["confidence"]    = "REJECT"
                    c["reject_reason"] = f"framing_plan_node_check(p1={p1_any},p2={p2_any})"
                    results.append(c)
                    continue
            else:
                # LENIENT: at least one endpoint required
                if not p1_any and not p2_any:
                    c["confidence"]    = "REJECT"
                    c["reject_reason"] = "no_structural_node"
                    results.append(c)
                    continue

        # ── Opening annotation rejection ──────────────────────────────────────
        # Floor openings (stairwells, elevator shafts) are drawn with diagonal
        # X-graphic lines to indicate the void.  If the candidate midpoint lies
        # within OPENING_SNAP_PT of any OPENING text label, reject it.
        if opening_regions:
            _cx = (c["x1"] + c["x2"]) / 2
            _cy = (c["y1"] + c["y2"]) / 2
            if any(math.hypot(_cx - ox, _cy - oy) < OPENING_SNAP_PT
                   for ox, oy in opening_regions):
                c["confidence"]    = "REJECT"
                c["reject_reason"] = "opening_annotation"
                results.append(c)
                continue

        c["confidence"] = base
        results.append(c)

    # ── Post-processing: annotation X-pair rejection ──────────────────────────
    # Detect pairs of MEDIUM candidates that form a perfect mirror X-symbol:
    #   • same center point (±NODE_SNAP_PT)
    #   • same bounding box (same x-range and y-range — perfect mirror)
    #   • bounding box smaller than XPAIR_MIN_BAY_FT in BOTH axes
    # Such pairs are annotation symbols (section markers, detail callouts, north
    # arrows) drawn as small crossing diagonals — not structural X-braces.
    # Real structural X-braces span at least one full bay (>> XPAIR_MIN_BAY_FT).
    if ppf > 0:
        min_bay_pt = XPAIR_MIN_BAY_FT * ppf
        med_idx = [i for i, c in enumerate(results)
                   if c.get("confidence") == "MEDIUM"]
        xpair_reject = set()
        for ii in range(len(med_idx)):
            i = med_idx[ii]
            a = results[i]
            for jj in range(ii + 1, len(med_idx)):
                j = med_idx[jj]
                b = results[j]
                # Same center?
                cxa = (a["x1"] + a["x2"]) / 2;  cya = (a["y1"] + a["y2"]) / 2
                cxb = (b["x1"] + b["x2"]) / 2;  cyb = (b["y1"] + b["y2"]) / 2
                if math.hypot(cxa - cxb, cya - cyb) > NODE_SNAP_PT:
                    continue
                # Same bounding box (perfect mirror)?
                ax0, ax1 = min(a["x1"],a["x2"]), max(a["x1"],a["x2"])
                ay0, ay1 = min(a["y1"],a["y2"]), max(a["y1"],a["y2"])
                bx0, bx1 = min(b["x1"],b["x2"]), max(b["x1"],b["x2"])
                by0, by1 = min(b["y1"],b["y2"]), max(b["y1"],b["y2"])
                if (abs(ax0-bx0) > NODE_SNAP_PT or abs(ax1-bx1) > NODE_SNAP_PT
                        or abs(ay0-by0) > NODE_SNAP_PT or abs(ay1-by1) > NODE_SNAP_PT):
                    continue
                # Bounding box smaller than minimum structural bay in both axes?
                bbox_w = ax1 - ax0
                bbox_h = ay1 - ay0
                if bbox_w < min_bay_pt and bbox_h < min_bay_pt:
                    xpair_reject.add(i)
                    xpair_reject.add(j)
        for idx in xpair_reject:
            results[idx]["confidence"]    = "REJECT"
            results[idx]["reject_reason"] = "annotation_xpair"

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE METRICS
# ══════════════════════════════════════════════════════════════════════════════

def page_metrics(classified: list, context: str = "unknown") -> dict:
    high   = [c for c in classified if c["confidence"] == "HIGH"]
    medium = [c for c in classified if c["confidence"] == "MEDIUM"]
    reject = [c for c in classified if c["confidence"] == "REJECT"]
    reasons: dict[str, int] = defaultdict(int)
    for c in reject:
        reasons[c.get("reject_reason") or "unknown"] += 1
    return {
        "total":          len(classified),
        "high":           len(high),
        "medium":         len(medium),
        "reject":         len(reject),
        "reject_reasons": dict(reasons),
        "high_lengths":   sorted([c["length_ft"] for c in high],   reverse=True),
        "medium_lengths": sorted([c["length_ft"] for c in medium], reverse=True),
        "context":        context,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  OVERLAY RENDERER
# ══════════════════════════════════════════════════════════════════════════════

_CONF_COLOR = {
    "HIGH":   (50,  205,  50),   # green
    "MEDIUM": (255, 195,   0),   # amber
    "REJECT": (100, 100, 100),   # grey
}

# Reject-reason colour overrides (shown instead of plain grey for key FP types)
_REJECT_COLORS = {
    "hatch_boundary":  (200,  80, 200),   # magenta
    "too_long":        (255,  80,  80),   # red
    "too_short":       ( 80,  80,  80),   # dark grey (same as reject)
    "density_cluster": ( 80,  80,  80),
}


def render_classified_overlay(page, classified, ppf, title, dpi=100):
    pix   = page.get_pixmap(dpi=dpi)
    img   = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    draw  = ImageDraw.Draw(img)
    scale = dpi / 72.0

    try:
        font = ImageFont.truetype("arial.ttf", 9)
    except Exception:
        font = ImageFont.load_default()

    # Draw REJECT first (bottom), then MEDIUM, then HIGH on top
    for conf in ("REJECT", "MEDIUM", "HIGH"):
        for c in classified:
            if c["confidence"] != conf:
                continue
            x1 = c["x1"] * scale;  y1 = c["y1"] * scale
            x2 = c["x2"] * scale;  y2 = c["y2"] * scale

            if conf == "REJECT":
                rr  = c.get("reject_reason") or ""
                col = _REJECT_COLORS.get(rr, _CONF_COLOR["REJECT"])
                w   = 2 if rr in ("hatch_boundary", "too_long") else 1
            else:
                col = _CONF_COLOR[conf]
                w   = 3 if conf == "HIGH" else 2

            draw.line([(x1, y1), (x2, y2)], fill=col, width=w)

            if conf != "REJECT":
                r = 3
                draw.ellipse([(x1-r, y1-r), (x1+r, y1+r)], fill=col)
                draw.ellipse([(x2-r, y2-r), (x2+r, y2+r)], fill=col)

            if conf == "HIGH":
                mx = (x1 + x2) / 2;  my = (y1 + y2) / 2
                txt = f"{c['length_ft']:.0f}ft"
                try:
                    bb = draw.textbbox((mx, my), txt, font=font)
                    draw.rectangle(bb, fill=(0, 0, 0))
                except Exception:
                    pass
                draw.text((mx, my), txt, fill=(50, 255, 50), font=font)

    # Context label in top-right
    ctx = classified[0]["page_context"] if classified else "unknown"
    ctx_color = {
        "braced_frame_elevation": (50, 255, 50),
        "framing_plan":           (100, 200, 255),
        "roof_plan":              (255, 200, 80),
        "foundation_plan":        (200, 160, 80),
        "detail":                 (255, 80,  80),
        "schedule_legend":        (255, 80,  80),
    }.get(ctx, (180, 180, 180))
    ctx_w = 160
    draw.rectangle([(img.width - ctx_w - 4, 4),
                    (img.width - 4, 18)], fill=(20, 20, 20))
    draw.text((img.width - ctx_w - 2, 5), ctx, fill=ctx_color, font=font)

    # Legend
    legend_items = [
        (_CONF_COLOR["HIGH"],   "HIGH   (>=15ft)"),
        (_CONF_COLOR["MEDIUM"], "MEDIUM (8-15ft, or roof plan)"),
        (_CONF_COLOR["REJECT"], "REJECT (cluster/short/long/context)"),
        (_REJECT_COLORS["hatch_boundary"], "REJECT:hatch_boundary"),
    ]
    ly = 6
    draw.rectangle([(4, 3), (210, 6 + len(legend_items) * 14 + 4)],
                   fill=(15, 15, 15))
    for col, txt in legend_items:
        draw.rectangle([(7, ly), (20, ly + 9)], fill=col)
        draw.text((23, ly), txt, fill=(210, 210, 210), font=font)
        ly += 13

    high_c   = sum(1 for c in classified if c["confidence"] == "HIGH")
    medium_c = sum(1 for c in classified if c["confidence"] == "MEDIUM")
    draw.text((6, ly + 2), f"H={high_c}  M={medium_c}  {title}",
              fill=(255, 255, 100), font=font)
    return img


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN — scan all PDFs, aggregate statistics
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", action="store_true",
                        help="Print per-page detail table")
    args = parser.parse_args()

    show_pages  = args.pages
    all_results = {}
    global_high = global_med = global_rej = 0

    # Context-level accumulators for summary
    ctx_high_counts: dict[str, int] = defaultdict(int)

    print("=" * 76)
    print("  BRACE CLASSIFIER v2 — Universal Multi-Project Detector")
    print("=" * 76)

    for pdf_name, scale_ratio in SCAN_PDFS:
        path = os.path.join(UPLOAD_DIR, pdf_name)
        if not os.path.exists(path):
            print(f"\n  [SKIP] {pdf_name}")
            continue

        ppf = scale_to_pts_per_foot(scale_ratio)
        doc = fitz.open(path)
        n   = len(doc)

        pdf_high = pdf_med = pdf_rej = 0
        pdf_pages_with_high = 0
        pdf_page_results    = {}
        overlay_pages       = []

        for pg in range(n):
            page = doc[pg]
            try:
                # Extract
                candidates       = extract_diagonals(page, ppf)
                ctx, ctx_score   = classify_page_context(page)
                scale_anns       = find_scale_annotations(page)
                nodes            = (extract_structural_nodes(page, ppf)
                                    if ctx in NODE_CHECK_CONTEXTS
                                    else None)
                openings         = extract_opening_regions(page)
                classified       = classify(candidates, ctx, scale_anns, ppf, nodes, openings)
                classified       = enrich_brace_results(classified, page)
                m                = page_metrics(classified, ctx)
                pdf_page_results[pg] = m
                pdf_high += m["high"]
                pdf_med  += m["medium"]
                pdf_rej  += m["reject"]
                if m["high"] > 0:
                    pdf_pages_with_high += 1
                    overlay_pages.append((pg, classified, ppf, page, ctx))
                    ctx_high_counts[ctx] += m["high"]
            except Exception:
                pass

        doc_summary = {
            "pages":           n,
            "pages_with_high": pdf_pages_with_high,
            "total_high":      pdf_high,
            "total_medium":    pdf_med,
            "total_reject":    pdf_rej,
            "page_detail":     pdf_page_results,
        }
        all_results[pdf_name] = doc_summary
        global_high += pdf_high
        global_med  += pdf_med
        global_rej  += pdf_rej

        short = pdf_name[:48]
        print(f"\n  {'─'*72}")
        print(f"  {short}")
        print(f"  scale=1:{scale_ratio:.0f}  pages={n}  "
              f"HIGH={pdf_high}  MED={pdf_med}  REJ={pdf_rej}  "
              f"p/HIGH={pdf_pages_with_high}")

        interesting = {pg: m for pg, m in pdf_page_results.items()
                       if m["high"] > 0 or m["medium"] > 0}

        if show_pages and interesting:
            print(f"\n    {'pg':>4}  {'H':>4}  {'M':>4}  {'R':>5}  "
                  f"{'context':<25}  {'reject reasons':<30}  high lengths (ft)")
            print(f"    {'─'*4}  {'─'*4}  {'─'*4}  {'─'*5}  {'─'*25}  "
                  f"{'─'*30}  {'─'*30}")
            for pg, m in sorted(interesting.items()):
                rr  = "  ".join(f"{k}:{v}" for k, v in m["reject_reasons"].items())
                hl  = " ".join(f"{x:.0f}" for x in m["high_lengths"][:8])
                ctx = m.get("context", "?")
                print(f"    {pg:>4}  {m['high']:>4}  {m['medium']:>4}  "
                      f"{m['reject']:>5}  {ctx:<25}  {rr:<30}  {hl}")
        elif interesting:
            pages_str = sorted(interesting.keys())
            print(f"    Pages with HIGH/MEDIUM: {pages_str}")
            top = sorted(interesting.items(), key=lambda x: x[1]["high"],
                         reverse=True)[:3]
            for pg, m in top:
                hl  = " ".join(f"{x:.0f}" for x in m["high_lengths"][:6])
                ctx = m.get("context", "?")
                print(f"    p{pg:02d}[{ctx[:20]}]: "
                      f"HIGH={m['high']} MED={m['medium']} lengths=[{hl}]")

        # Render overlays (first 4 pages with HIGH braces per PDF)
        pdf_slug = re.sub(r'[^A-Za-z0-9_]', '_', pdf_name[:30])
        rendered = 0
        for (pg, classified, ppf_, page, ctx) in overlay_pages:
            if rendered >= 4:
                break
            if sum(1 for c in classified if c["confidence"] == "HIGH") == 0:
                continue
            img = render_classified_overlay(page, classified, ppf_,
                                            f"p{pg}[{ctx[:12]}]")
            out = os.path.join(OUT_DIR, f"{pdf_slug}__p{pg:03d}.png")
            img.save(out)
            rendered += 1

        doc.close()

    # ── Global summary ────────────────────────────────────────────────────────
    total = global_high + global_med + global_rej or 1
    print(f"\n{'='*76}")
    print(f"  GLOBAL SUMMARY")
    print(f"{'='*76}")
    print(f"\n  Total candidates (all PDFs, all pages):")
    print(f"    HIGH   : {global_high:>6}  ({100*global_high/total:.1f}%)")
    print(f"    MEDIUM : {global_med:>6}  ({100*global_med/total:.1f}%)")
    print(f"    REJECT : {global_rej:>6}  ({100*global_rej/total:.1f}%)")
    print(f"    TOTAL  : {global_high+global_med+global_rej:>6}")

    print(f"\n  HIGH candidates by page context:")
    for ctx in ["braced_frame_elevation", "framing_plan", "roof_plan",
                "foundation_plan", "detail", "schedule_legend", "unknown"]:
        n = ctx_high_counts.get(ctx, 0)
        if n > 0:
            print(f"    {ctx:<30}: {n:>5}")

    print(f"\n  {'PDF':<48}  {'HIGH':>5}  {'MED':>5}  {'REJ':>6}  {'p/HIGH':>6}")
    print(f"  {'─'*48}  {'─'*5}  {'─'*5}  {'─'*6}  {'─'*6}")
    for pdf_name, _ in SCAN_PDFS:
        if pdf_name not in all_results:
            continue
        r = all_results[pdf_name]
        print(f"  {pdf_name[:48]:<48}  {r['total_high']:>5}  "
              f"{r['total_medium']:>5}  {r['total_reject']:>6}  "
              f"{r['pages_with_high']:>6}")

    # ── Save JSON ─────────────────────────────────────────────────────────────
    serializable = {}
    for pdf, data in all_results.items():
        serializable[pdf] = {
            "pages":           data["pages"],
            "pages_with_high": data["pages_with_high"],
            "total_high":      data["total_high"],
            "total_medium":    data["total_medium"],
            "total_reject":    data["total_reject"],
            "page_detail": {
                str(pg): {
                    "high":           m["high"],
                    "medium":         m["medium"],
                    "reject":         m["reject"],
                    "context":        m.get("context", "unknown"),
                    "high_lengths":   m["high_lengths"][:20],
                    "medium_lengths": m["medium_lengths"][:20],
                    "reject_reasons": m["reject_reasons"],
                }
                for pg, m in data["page_detail"].items()
            },
        }

    json_path = os.path.join(OUT_DIR, "brace_classifier_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2)

    print(f"\n  Overlays : {OUT_DIR}")
    print(f"  JSON     : {json_path}")
    print(f"{'='*76}\n")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
