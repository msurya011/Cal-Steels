"""
Brace Extraction Validation Scorer
------------------------------------
Reads the annotated validation_candidates.csv and calculates:
  - True Positives / False Positives per category
  - Precision / Recall
  - Breakdown by page context and confidence level
  - Which false-positive categories dominate

Run after filling in the 'category' column in validation_candidates.csv:
  python _validation_score.py

Category codes:
  TP   — Real structural brace
  FP_J — Joist mistaken as brace
  FP_H — Hatch geometry
  FP_R — Roof graphic / slope indicator
  FP_O — Opening marker / stair framing
  FP_A — Annotation geometry
  FP_U — Unknown false positive
  (blank) — not yet annotated
"""

import os, sys, io, csv
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE     = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "validation_candidates.csv")

FP_CATEGORIES = {"FP_J", "FP_H", "FP_R", "FP_O", "FP_A", "FP_U"}
TP_CATEGORY   = "TP"

if not os.path.exists(CSV_PATH):
    print(f"ERROR: {CSV_PATH} not found. Run _validation_report.py first.")
    sys.exit(1)

rows = []
with open(CSV_PATH, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

annotated   = [r for r in rows if r["category"].strip()]
unannotated = [r for r in rows if not r["category"].strip()]

if not annotated:
    print("No annotated rows yet. Fill in the 'category' column first.")
    sys.exit(0)

# ── Aggregate ─────────────────────────────────────────────────────────────────

tp_total = sum(1 for r in annotated if r["category"] == TP_CATEGORY)
fp_total = sum(1 for r in annotated if r["category"] in FP_CATEGORIES)

# FP breakdown by category
fp_by_cat: dict[str, int] = defaultdict(int)
for r in annotated:
    if r["category"] in FP_CATEGORIES:
        fp_by_cat[r["category"]] += 1

# TP/FP by page context
ctx_tp: dict[str, int] = defaultdict(int)
ctx_fp: dict[str, int] = defaultdict(int)
for r in annotated:
    ctx = r["context"]
    if r["category"] == TP_CATEGORY:
        ctx_tp[ctx] += 1
    elif r["category"] in FP_CATEGORIES:
        ctx_fp[ctx] += 1

# TP/FP by confidence
conf_tp: dict[str, int] = defaultdict(int)
conf_fp: dict[str, int] = defaultdict(int)
for r in annotated:
    conf = r["confidence"]
    if r["category"] == TP_CATEGORY:
        conf_tp[conf] += 1
    elif r["category"] in FP_CATEGORIES:
        conf_fp[conf] += 1

# TP/FP by PDF
pdf_tp: dict[str, int] = defaultdict(int)
pdf_fp: dict[str, int] = defaultdict(int)
for r in annotated:
    pdf = r["pdf"]
    if r["category"] == TP_CATEGORY:
        pdf_tp[pdf] += 1
    elif r["category"] in FP_CATEGORIES:
        pdf_fp[pdf] += 1

# ── Precision / Recall ────────────────────────────────────────────────────────
# Precision = TP / (TP + FP)
# Recall requires knowing total true braces in each drawing (manual count needed)
# We report precision; recall section asks the user to fill in missed counts.

precision = tp_total / (tp_total + fp_total) if (tp_total + fp_total) > 0 else 0.0

RECALL_NOTE = """
  RECALL NOTE
  -----------
  To compute recall you need the total number of real braces in each drawing.
  Add a row to validation_missed.csv for each brace that was NOT extracted:
    pdf, page, notes
  Then recall = TP / (TP + missed_count).
"""

# ── Print report ──────────────────────────────────────────────────────────────

print("=" * 72)
print("  BRACE EXTRACTION VALIDATION SCORE")
print("=" * 72)
print()
print(f"  Annotated   : {len(annotated)}  /  {len(rows)}  total candidates")
if unannotated:
    print(f"  Unannotated : {len(unannotated)}  (not included in scores below)")
print()
print(f"  True Positives  (TP) : {tp_total}")
print(f"  False Positives (FP) : {fp_total}")
print(f"  Precision            : {precision:.1%}")
print()

print("  FP breakdown by category:")
for cat in sorted(fp_by_cat, key=lambda c: -fp_by_cat[c]):
    label = {
        "FP_J": "Joist mistaken as brace",
        "FP_H": "Hatch geometry",
        "FP_R": "Roof graphic / slope indicator",
        "FP_O": "Opening marker / stair framing",
        "FP_A": "Annotation geometry",
        "FP_U": "Unknown",
    }.get(cat, cat)
    pct = fp_by_cat[cat] / fp_total * 100 if fp_total else 0
    print(f"    {cat}  {fp_by_cat[cat]:>4}  ({pct:.0f}%)  {label}")

print()
print("  Results by page context:")
all_ctxs = sorted(set(list(ctx_tp.keys()) + list(ctx_fp.keys())))
for ctx in all_ctxs:
    tp = ctx_tp.get(ctx, 0)
    fp = ctx_fp.get(ctx, 0)
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    print(f"    {ctx:<30}  TP={tp:>4}  FP={fp:>4}  prec={prec:.0%}")

print()
print("  Results by confidence level:")
for conf in ["HIGH", "MEDIUM"]:
    tp   = conf_tp.get(conf, 0)
    fp   = conf_fp.get(conf, 0)
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    print(f"    {conf:<8}  TP={tp:>4}  FP={fp:>4}  prec={prec:.0%}")

print()
print("  Results by PDF:")
all_pdfs = sorted(set(list(pdf_tp.keys()) + list(pdf_fp.keys())))
for pdf in all_pdfs:
    tp   = pdf_tp.get(pdf, 0)
    fp   = pdf_fp.get(pdf, 0)
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    print(f"    {pdf[:48]:<48}  TP={tp:>3}  FP={fp:>3}  prec={prec:.0%}")

print()
print(RECALL_NOTE)
print("=" * 72)
