"""
Structural Brace Diagnostic Overlay
------------------------------------
Renders per-page overlay images that colour-code every diagonal candidate by
what a structural connectivity validation layer would think of it.

Colour key
----------
  GREEN  (0,200,80)    — accepted brace  : endpoint(s) land on a structural node
                          (beam/column intersection)
  AMBER  (255,180,0)   — probable brace  : one endpoint on a node, other near frame
  RED    (220,40,40)   — annotation geom : endpoint near text / drawing boundary only
  PURPLE (180,0,220)   — hatch/fill diag : surrounded by same-angle neighbours
  GREY   (120,120,120) — unconnected     : no structural node at either endpoint

Structural nodes are derived from:
  • All near-horizontal + near-vertical line intersections  (beam/column grid)
  • Text centroids whose content matches COL / HSS / W\d+ / column labels

No brace-specific thresholds changed.  Run:
  cd D:\Steel-ghost\steelgenie\backend
  python _diagnostic_overlay.py

Output PNG files land in  brace_classifier_output/diag/
"""

import os, sys, io, re, math, fitz
from PIL import Image, ImageDraw, ImageFont
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import brace_classifier as bc

OUT_DIR = os.path.join(bc.OUT_DIR, "diag")
os.makedirs(OUT_DIR, exist_ok=True)

# ── Tunable connectivity parameters (not brace geometry) ─────────────────────
NODE_SNAP_PT    = 30.0   # pt radius — endpoint must be within this of a node
HATCH_MIN_NBRS  = 5      # same-angle neighbours in bbox → hatch diagonal
TEXT_SNAP_PT    = 40.0   # pt radius — endpoint near text centroid → annotation

# ── Patterns that identify structural text labels ─────────────────────────────
_STRUCT_LABEL = re.compile(
    r'\b(COL|HSS|W\d|TS\d|MC\d|C\d|L\d|BF[-–]\d|BRACE|X-BRACE|K-BRACE)\b',
    re.I)


# ══════════════════════════════════════════════════════════════════════════════
#  STRUCTURAL NODE EXTRACTION
#  Nodes = intersections of near-H and near-V lines (the column/beam grid)
# ══════════════════════════════════════════════════════════════════════════════

def extract_structural_nodes(page) -> list:
    """
    Return list of (x, y) structural node candidates from the page.

    Two sources:
    1. Grid intersections — every near-horizontal line crossed with every
       near-vertical line (threshold ±10°).  Intersection point added if it
       lies within both segments' bounding boxes (with NODE_SNAP_PT tolerance).

    2. Structural text centroids — spans whose text matches _STRUCT_LABEL
       (COL, HSS, W-shape, BF-X, BRACE …).
    """
    h_lines = []   # (x1,y1,x2,y2)
    v_lines = []

    try:
        for d in page.get_drawings():
            for item in d.get("items", []):
                if item[0] != "l":
                    continue
                p1, p2 = item[1], item[2]
                dx = p2.x - p1.x
                dy = p2.y - p1.y
                ln = math.hypot(dx, dy)
                if ln < 20:
                    continue
                ang = abs(math.degrees(math.atan2(dy, dx))) % 180
                ang_h = min(ang, 180 - ang)
                if ang_h <= 10:
                    h_lines.append((p1.x, p1.y, p2.x, p2.y))
                elif ang_h >= 80:
                    v_lines.append((p1.x, p1.y, p2.x, p2.y))
    except Exception:
        pass

    nodes = []
    tol = NODE_SNAP_PT

    for (hx1, hy1, hx2, hy2) in h_lines:
        for (vx1, vy1, vx2, vy2) in v_lines:
            # Intersection of infinite lines
            # Parameterize H as P + t*(Q-P), V as R + s*(S-R)
            hx = hx2 - hx1;  hy = hy2 - hy1
            vx = vx2 - vx1;  vy = vy2 - vy1
            denom = hx * vy - hy * vx
            if abs(denom) < 1e-6:
                continue
            dx = vx1 - hx1;  dy = vy1 - hy1
            t = (dx * vy - dy * vx) / denom
            s = (dx * hy - dy * hx) / denom
            # Check within segments (with tolerance)
            seg_tol = tol / max(math.hypot(hx, hy), math.hypot(vx, vy), 1)
            if -seg_tol <= t <= 1 + seg_tol and -seg_tol <= s <= 1 + seg_tol:
                ix = hx1 + t * hx
                iy = hy1 + t * hy
                nodes.append((ix, iy))

    # Structural text labels
    try:
        td = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        for block in td.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span.get("text", "").strip()
                    if _STRUCT_LABEL.search(t):
                        ox = span.get("origin", (0, 0))[0]
                        oy = span.get("origin", (0, 0))[1]
                        nodes.append((ox, oy))
    except Exception:
        pass

    # Deduplicate nodes within NODE_SNAP_PT
    merged = []
    for (nx, ny) in nodes:
        if not any(math.hypot(nx - mx, ny - my) < NODE_SNAP_PT
                   for (mx, my) in merged):
            merged.append((nx, ny))

    return merged


def endpoint_on_node(cand: dict, nodes: list) -> tuple:
    """
    Returns (p1_hit, p2_hit) booleans — whether each endpoint of the candidate
    is within NODE_SNAP_PT of any structural node.
    """
    p1_hit = any(math.hypot(cand["x1"] - nx, cand["y1"] - ny) < NODE_SNAP_PT
                 for (nx, ny) in nodes)
    p2_hit = any(math.hypot(cand["x2"] - nx, cand["y2"] - ny) < NODE_SNAP_PT
                 for (nx, ny) in nodes)
    return p1_hit, p2_hit


# ══════════════════════════════════════════════════════════════════════════════
#  ANNOTATION GEOMETRY DETECTION
#  Endpoints near text labels (without structural meaning) → annotation
# ══════════════════════════════════════════════════════════════════════════════

def extract_text_centroids(page) -> list:
    """All text span origins on the page."""
    pts = []
    try:
        td = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        for block in td.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    ox = span.get("origin", (0, 0))[0]
                    oy = span.get("origin", (0, 0))[1]
                    pts.append((ox, oy))
    except Exception:
        pass
    return pts


def endpoint_near_text(cand: dict, text_pts: list) -> bool:
    """True if BOTH endpoints are near text but NOT near any structural node."""
    p1_txt = any(math.hypot(cand["x1"] - tx, cand["y1"] - ty) < TEXT_SNAP_PT
                 for (tx, ty) in text_pts)
    p2_txt = any(math.hypot(cand["x2"] - tx, cand["y2"] - ty) < TEXT_SNAP_PT
                 for (tx, ty) in text_pts)
    return p1_txt and p2_txt


# ══════════════════════════════════════════════════════════════════════════════
#  HATCH DIAGONAL DETECTION
#  Surrounded by same-angle neighbours within bounding box
# ══════════════════════════════════════════════════════════════════════════════

def is_hatch_diagonal(cand: dict, all_cands: list) -> bool:
    ang   = cand["angle_from_h"]
    bx0   = min(cand["x1"], cand["x2"])
    by0   = min(cand["y1"], cand["y2"])
    bx1   = max(cand["x1"], cand["x2"])
    by1   = max(cand["y1"], cand["y2"])
    pad   = 20.0
    count = 0
    for other in all_cands:
        if other is cand:
            continue
        if abs(other["angle_from_h"] - ang) > 5.0:
            continue
        mx = (other["x1"] + other["x2"]) / 2
        my = (other["y1"] + other["y2"]) / 2
        if (bx0 - pad <= mx <= bx1 + pad and
                by0 - pad <= my <= by1 + pad):
            count += 1
            if count >= HATCH_MIN_NBRS:
                return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  CONNECTIVITY CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

CONN_COLOR = {
    "accepted":    (0,   200,  80),   # green  — both endpoints on nodes
    "probable":    (255, 180,   0),   # amber  — one endpoint on a node
    "hatch":       (180,   0, 220),   # purple — hatch diagonal
    "annotation":  (220,  40,  40),   # red    — both endpoints near text only
    "unconnected": (120, 120, 120),   # grey   — no node at either endpoint
}

CONN_LABEL = {
    "accepted":    "ACCEPTED  (both endpoints on structural nodes)",
    "probable":    "PROBABLE  (one endpoint on structural node)",
    "hatch":       "HATCH     (same-angle neighbours in bbox)",
    "annotation":  "ANNOTATION (endpoints near text only)",
    "unconnected": "UNCONNECTED (no structural node at endpoints)",
}


def classify_connectivity(cand: dict, nodes: list,
                          text_pts: list, all_cands: list) -> str:
    p1h, p2h = endpoint_on_node(cand, nodes)

    if p1h and p2h:
        return "accepted"
    if p1h or p2h:
        return "probable"
    if is_hatch_diagonal(cand, all_cands):
        return "hatch"
    if endpoint_near_text(cand, text_pts):
        return "annotation"
    return "unconnected"


# ══════════════════════════════════════════════════════════════════════════════
#  OVERLAY RENDERER
# ══════════════════════════════════════════════════════════════════════════════

def render_diagnostic(page, candidates, nodes, conn_labels, dpi=120):
    pix   = page.get_pixmap(dpi=dpi)
    img   = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    draw  = ImageDraw.Draw(img)
    scale = dpi / 72.0

    try:
        font  = ImageFont.truetype("arial.ttf", 9)
        font2 = ImageFont.truetype("arial.ttf", 8)
    except Exception:
        font = font2 = ImageFont.load_default()

    # Draw order: hatch < unconnected < annotation < probable < accepted
    order = ["hatch", "unconnected", "annotation", "probable", "accepted"]
    by_cat = defaultdict(list)
    for cand, cat in zip(candidates, conn_labels):
        by_cat[cat].append(cand)

    for cat in order:
        col = CONN_COLOR[cat]
        w   = 3 if cat in ("accepted", "probable") else 2
        for c in by_cat[cat]:
            x1 = c["x1"] * scale;  y1 = c["y1"] * scale
            x2 = c["x2"] * scale;  y2 = c["y2"] * scale
            draw.line([(x1, y1), (x2, y2)], fill=col, width=w)
            r = 4 if cat == "accepted" else 3
            draw.ellipse([(x1-r, y1-r), (x1+r, y1+r)], fill=col)
            draw.ellipse([(x2-r, y2-r), (x2+r, y2+r)], fill=col)

    # Structural nodes (cyan dots)
    for (nx, ny) in nodes:
        sx, sy = nx * scale, ny * scale
        r = 4
        draw.ellipse([(sx-r, sy-r), (sx+r, sy+r)],
                     outline=(0, 220, 220), width=2)

    # Legend
    ly = 6
    legend_w = 320
    draw.rectangle([(4, 3), (legend_w + 6, 6 + len(CONN_COLOR) * 14 + 20)],
                   fill=(15, 15, 15))
    for cat in order:
        col = CONN_COLOR[cat]
        draw.rectangle([(7, ly), (20, ly + 9)], fill=col)
        draw.text((24, ly), CONN_LABEL[cat], fill=(220, 220, 220), font=font2)
        ly += 13
    draw.rectangle([(7, ly), (20, ly + 9)], outline=(0, 220, 220), width=2)
    draw.text((24, ly), "STRUCTURAL NODE (beam/col intersection or label)",
              fill=(0, 220, 220), font=font2)

    # Counts
    counts = {cat: len(v) for cat, v in by_cat.items()}
    summary = "  ".join(f"{cat[:3].upper()}={counts.get(cat,0)}" for cat in order)
    draw.text((6, ly + 16), summary, fill=(255, 255, 100), font=font)

    return img


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

DIAG_PAGES = [
    # (pdf, page_index, scale, label)
    ("Structural snaps.pdf",                                    5,  96, "snaps_p5_elevation"),
    ("Structural snaps.pdf",                                    6,  96, "snaps_p6_elevation"),
    ("Structural snaps.pdf",                                    2,  96, "snaps_p2_framing"),
    ("#Structural binder.pdf",                                 12,  64, "binder_p12_framing"),
    ("07_STRUCTURAL_COMBINED.pdf",                             47, 192, "07comb_p47_elev"),
    ("2026.03.27_Bayhealth Sussex MOB_DD Set_Structural.pdf",   5, 192, "bayhealth_p5_framing"),
    ("02 Struct 98 Spruce_2026-03-13_BID.pdf",                  3,  96, "spruce_p3_framing"),
    ("STRUCTURAL 5-26-26.pdf",                                  2,  96, "526_p2_framing"),
]

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")

print("=" * 70)
print("  STRUCTURAL CONNECTIVITY DIAGNOSTIC")
print("=" * 70)

for (pdf, pg_idx, scale, label) in DIAG_PAGES:
    path = os.path.join(UPLOAD_DIR, pdf)
    if not os.path.exists(path):
        print(f"  [SKIP] {pdf}")
        continue

    doc = fitz.open(path)
    if pg_idx >= len(doc):
        doc.close()
        continue

    page = doc[pg_idx]
    ppf  = bc.scale_to_pts_per_foot(scale)

    candidates = bc.extract_diagonals(page, ppf)
    nodes      = extract_structural_nodes(page)
    text_pts   = extract_text_centroids(page)

    # Filter to those that pass current 4-layer classifier (HIGH or MEDIUM)
    ctx, _   = bc.classify_page_context(page)
    scales   = bc.find_scale_annotations(page)
    clfd     = bc.classify(candidates, ctx, scales, ppf)
    passing  = [c for c in clfd if c["confidence"] in ("HIGH", "MEDIUM")]

    conn_labels = [
        classify_connectivity(c, nodes, text_pts, passing)
        for c in passing
    ]

    counts = defaultdict(int)
    for cat in conn_labels:
        counts[cat] += 1

    print(f"\n  [{label}]  ctx={ctx}  nodes={len(nodes)}  passing={len(passing)}")
    for cat in ["accepted", "probable", "annotation", "hatch", "unconnected"]:
        n = counts.get(cat, 0)
        if n:
            print(f"    {cat:<14}: {n}")

    img = render_diagnostic(page, passing, nodes, conn_labels, dpi=120)
    out = os.path.join(OUT_DIR, f"{label}.png")
    img.save(out)
    print(f"    → {out}")

    doc.close()

print(f"\n{'='*70}")
print(f"  Overlay images saved to: {OUT_DIR}")
print(f"{'='*70}")
