"""
Brace Extraction Validation Report
------------------------------------
Runs the CURRENT 4-layer extraction engine (no new filters) across all
available PDFs and produces:

  1. Per-page overlay PNGs — each candidate numbered, HIGH green / MEDIUM amber
  2. validation_candidates.csv — one row per candidate, with blank "category"
     and "notes" columns for manual annotation

Manual annotation categories (fill in the "category" column):
  TP   — Real structural brace (true positive)
  FP_J — Joist mistaken as brace
  FP_H — Hatch geometry (fill pattern diagonal)
  FP_R — Roof graphic / slope indicator
  FP_O — Opening marker / stair framing diagonal
  FP_A — Annotation geometry (north arrow, detail symbol)
  FP_U — Unknown false positive

After annotation run:  python _validation_score.py

Output
------
  validation_report/        overlay PNGs (one per page with any HIGH/MEDIUM)
  validation_candidates.csv full candidate list for annotation
  validation_summary.txt    count summary
"""

import os, sys, io, re, csv, math, fitz
from PIL import Image, ImageDraw, ImageFont
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import brace_classifier as bc

HERE       = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(HERE, "uploads")
OUT_DIR    = os.path.join(HERE, "validation_report")
CSV_PATH   = os.path.join(HERE, "validation_candidates.csv")
SUMMARY    = os.path.join(HERE, "validation_summary.txt")

os.makedirs(OUT_DIR, exist_ok=True)

# ── PDFs and their scale ratios ───────────────────────────────────────────────
PDFS = [
    ("Structural snaps.pdf",                                     96.0),
    ("#Structural binder.pdf",                                   64.0),
    ("07_STRUCTURAL_COMBINED.pdf",                              192.0),
    ("2026.03.27_Bayhealth Sussex MOB_DD Set_Structural.pdf",   192.0),
    ("02 Struct 98 Spruce_2026-03-13_BID.pdf",                   96.0),
    ("STRUCTURAL 5-26-26.pdf",                                   96.0),
    ("Latest_Structural dwg_Binder (Addendum-02).pdf",           96.0),
    ("04_-_STRUCTURAL.pdf",                                      96.0),
    ("NCU SherMan_Structural.pdf",                               96.0),
    ("Pages from 2026.05.08_FF Martha Washington Building - Issued for Pricing.pdf", 96.0),
]

DPI = 110   # render DPI for overlay images

# ── Colours ───────────────────────────────────────────────────────────────────
COL_HIGH   = (20,  200,  60)   # green
COL_MED    = (255, 175,   0)   # amber
COL_ID_BG  = (10,  10,  10)   # label background
COL_ID_TXT = (255, 255, 255)   # label text


def slug(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9_]', '_', name[:40])


def render_page_overlay(page, candidates_with_id, dpi=DPI):
    """
    Returns a PIL image of the page with each candidate drawn and labelled.
    candidates_with_id : list of (global_id, candidate_dict)
    """
    pix   = page.get_pixmap(dpi=dpi)
    img   = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    draw  = ImageDraw.Draw(img)
    scale = dpi / 72.0

    try:
        font_big = ImageFont.truetype("arial.ttf", 11)
        font_sm  = ImageFont.truetype("arial.ttf", 8)
    except Exception:
        font_big = ImageFont.load_default()
        font_sm  = font_big

    # Draw MEDIUM first (below HIGH)
    for conf_order in ("MEDIUM", "HIGH"):
        for (gid, c) in candidates_with_id:
            if c["confidence"] != conf_order:
                continue
            col = COL_HIGH if conf_order == "HIGH" else COL_MED
            lw  = 3 if conf_order == "HIGH" else 2

            x1 = c["x1"] * scale;  y1 = c["y1"] * scale
            x2 = c["x2"] * scale;  y2 = c["y2"] * scale

            draw.line([(x1, y1), (x2, y2)], fill=col, width=lw)

            # Endpoint dots
            r = 4 if conf_order == "HIGH" else 3
            draw.ellipse([(x1-r, y1-r), (x1+r, y1+r)], fill=col)
            draw.ellipse([(x2-r, y2-r), (x2+r, y2+r)], fill=col)

            # ID label at midpoint
            mx = (x1 + x2) / 2
            my = (y1 + y2) / 2
            label = str(gid)
            try:
                bb = draw.textbbox((0, 0), label, font=font_big)
                tw = bb[2] - bb[0];  th = bb[3] - bb[1]
            except Exception:
                tw = len(label) * 6;  th = 10
            pad = 2
            lx = mx - tw / 2 - pad
            ly = my - th / 2 - pad
            draw.rectangle([(lx, ly), (lx + tw + pad*2, ly + th + pad*2)],
                           fill=COL_ID_BG)
            draw.text((lx + pad, ly + pad), label, fill=col, font=font_big)

    # Legend (top-left box)
    legend = [
        (COL_HIGH, "HIGH (≥15 ft) — candidate IDs in green"),
        (COL_MED,  "MEDIUM (8–15 ft) — candidate IDs in amber"),
    ]
    lx0, ly0 = 5, 5
    box_h = len(legend) * 14 + 8
    draw.rectangle([(lx0, ly0), (lx0 + 310, ly0 + box_h)], fill=(15, 15, 15))
    ly = ly0 + 4
    for col, txt in legend:
        draw.rectangle([(lx0+4, ly), (lx0+16, ly+9)], fill=col)
        draw.text((lx0+20, ly), txt, fill=(220, 220, 220), font=font_sm)
        ly += 13

    return img


# ── Main scan loop ─────────────────────────────────────────────────────────────

all_rows   = []
global_id  = 1
page_count = 0

# Per-context accumulators
ctx_counts  = defaultdict(int)
conf_counts = defaultdict(int)

print("=" * 72)
print("  BRACE EXTRACTION VALIDATION REPORT")
print("=" * 72)

for (pdf_name, scale_ratio) in PDFS:
    path = os.path.join(UPLOAD_DIR, pdf_name)
    if not os.path.exists(path):
        print(f"\n  [SKIP] {pdf_name}")
        continue

    doc = fitz.open(path)
    ppf = bc.scale_to_pts_per_foot(scale_ratio)
    pdf_slug = slug(pdf_name)

    print(f"\n  {pdf_name[:60]}")
    print(f"  scale=1:{scale_ratio:.0f}   pages={len(doc)}")

    for pg in range(len(doc)):
        page = doc[pg]
        try:
            candidates = bc.extract_diagonals(page, ppf)
            ctx, _     = bc.classify_page_context(page)
            scales     = bc.find_scale_annotations(page)
            classified = bc.classify(candidates, ctx, scales, ppf)

            passing = [c for c in classified
                       if c["confidence"] in ("HIGH", "MEDIUM")]
            if not passing:
                continue

            page_w = page.rect.width
            page_h = page.rect.height

            # Assign global IDs and build overlay
            with_ids = []
            for c in passing:
                with_ids.append((global_id, c))

                mx = (c["x1"] + c["x2"]) / 2
                my = (c["y1"] + c["y2"]) / 2

                all_rows.append({
                    "id":          global_id,
                    "pdf":         pdf_name,
                    "page":        pg,
                    "context":     ctx,
                    "confidence":  c["confidence"],
                    "length_ft":   round(c["length_ft"], 2),
                    "angle_deg":   round(c["angle_from_h"], 1),
                    "x1_pt":       round(c["x1"], 1),
                    "y1_pt":       round(c["y1"], 1),
                    "x2_pt":       round(c["x2"], 1),
                    "y2_pt":       round(c["y2"], 1),
                    "bx1":         round(c["x1"] / page_w, 4),
                    "by1":         round(c["y1"] / page_h, 4),
                    "bx2":         round(c["x2"] / page_w, 4),
                    "by2":         round(c["y2"] / page_h, 4),
                    "mx_frac":     round(mx / page_w, 4),
                    "my_frac":     round(my / page_h, 4),
                    "image_file":  f"{pdf_slug}__p{pg:03d}.png",
                    "category":    "",   # ← fill in manually
                    "notes":       "",   # ← optional notes
                })
                ctx_counts[ctx]            += 1
                conf_counts[c["confidence"]] += 1
                global_id += 1

            # Render overlay
            img  = render_page_overlay(page, with_ids)
            out  = os.path.join(OUT_DIR, f"{pdf_slug}__p{pg:03d}.png")
            img.save(out)
            page_count += 1

            h_cnt = sum(1 for (_, c) in with_ids if c["confidence"] == "HIGH")
            m_cnt = sum(1 for (_, c) in with_ids if c["confidence"] == "MEDIUM")
            ids   = [str(gid) for (gid, _) in with_ids]
            print(f"    p{pg:03d}  ctx={ctx:<24}  H={h_cnt} M={m_cnt}"
                  f"  IDs=[{','.join(ids)}]")

        except Exception as e:
            print(f"    p{pg:03d}  ERROR: {e}")

    doc.close()

# ── Write CSV ─────────────────────────────────────────────────────────────────

FIELDS = [
    "id", "pdf", "page", "context", "confidence",
    "length_ft", "angle_deg",
    "x1_pt", "y1_pt", "x2_pt", "y2_pt",
    "bx1", "by1", "bx2", "by2",
    "mx_frac", "my_frac",
    "image_file",
    "category",   # ← annotate here
    "notes",      # ← optional
]

with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(all_rows)

# ── Write summary ─────────────────────────────────────────────────────────────

summary_lines = [
    "=" * 72,
    "  BRACE EXTRACTION VALIDATION SUMMARY",
    "=" * 72,
    "",
    f"  Total candidates (HIGH+MEDIUM) : {len(all_rows)}",
    f"  Pages with candidates          : {page_count}",
    "",
    "  Breakdown by confidence:",
    f"    HIGH   : {conf_counts['HIGH']}",
    f"    MEDIUM : {conf_counts['MEDIUM']}",
    "",
    "  Breakdown by page context:",
]
for ctx in ["braced_frame_elevation", "framing_plan", "roof_plan",
            "foundation_plan", "detail", "schedule_legend", "unknown"]:
    n = ctx_counts.get(ctx, 0)
    if n:
        summary_lines.append(f"    {ctx:<30}: {n}")

summary_lines += [
    "",
    "  CSV for annotation:",
    f"    {CSV_PATH}",
    "",
    "  Overlay images:",
    f"    {OUT_DIR}",
    "",
    "  ANNOTATION INSTRUCTIONS",
    "  -----------------------",
    "  Open each PNG in validation_report/ alongside the CSV.",
    "  Find each candidate ID on the image.",
    "  Fill in the 'category' column with one of:",
    "",
    "    TP   — Real structural brace (true positive)",
    "    FP_J — Joist mistaken as brace",
    "    FP_H — Hatch geometry (fill pattern diagonal)",
    "    FP_R — Roof graphic / slope indicator",
    "    FP_O — Opening marker / stair framing diagonal",
    "    FP_A — Annotation geometry (north arrow, detail symbol)",
    "    FP_U — Unknown false positive",
    "",
    "  After annotation, run:  python _validation_score.py",
    "=" * 72,
]

summary_txt = "\n".join(summary_lines)
with open(SUMMARY, "w", encoding="utf-8") as f:
    f.write(summary_txt)

print()
print(summary_txt)
