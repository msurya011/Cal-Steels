"""
Corpus health report: where does grid extraction actually fail?

The pipeline has to work on whatever PDF a user uploads, so the question that
matters is not "does it work on this sheet" but "across every page we have,
what stops it, and how often". This walks every page of every PDF in uploads/
and classifies the outcome into one bucket, then ranks the buckets.

Buckets, checked in order (first match wins, so each page counts once):

  SCANNED          no extractable text at all -- a raster scan. The vector
                   pass cannot help; this is the vision pass's job.
  NO_TEXT_GRIDS    text exists, but no label sits inside a circle. Either not
                   a plan sheet (notes, schedules, details) or the bubbles are
                   images.
  NOT_A_PLAN       bubbles exist but no scale note and no dimension strings --
                   almost always a schedule or detail sheet.
  NO_SCALE         grids found, but no scale printed and none derivable.
                   Every distance is then a guess.
  SCALE_WRONG      grids and dimensions found, but the measured bays disagree
                   with the printed ones by a median of more than a foot --
                   the classic signature of a misread scale, since the error
                   is multiplicative and hits every bay at once.
  NO_DIMENSIONS    grids found, scale fine, but nothing to check against.
  GRIDS_ONE_AXIS   only one axis resolved -- half the plan is unmeasurable.
  HEALTHY          grids on both axes, and the geometry agrees with the
                   sheet's own printed dimensions on most bays.

Usage:
    python corpus_health.py [start_index] [end_index]   # chunked, appends JSON
    python corpus_health.py --report                    # summarise the log
"""

import os
import sys
import glob
import json
import statistics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz

LOG = "debug/corpus_health.jsonl"


def classify(pdf_path, page_no):
    from app.engineering.grid_geometry_pass import (
        run_deterministic_geometry_pass, _find_confirmed_bubbles,
        _collect_dim_spans, detect_scale_factor, parse_dimension_string,
    )

    doc = fitz.open(pdf_path)
    page = doc[page_no]
    text_dict = page.get_text("dict")
    raw_text = page.get_text().strip()
    has_text = len(raw_text) > 40
    bubbles = _find_confirmed_bubbles(page, text_dict)
    dims = _collect_dim_spans(page, text_dict)
    ppf, scale_str, explicit = detect_scale_factor(text_dict)
    doc.close()

    rec = {"file": os.path.basename(pdf_path), "page": page_no,
           "bubbles": len(bubbles), "dim_texts": len(dims),
           "scale_explicit": explicit, "scale_str": scale_str[:40]}

    if not has_text:
        rec["bucket"] = "SCANNED"
        return rec
    if not bubbles:
        rec["bucket"] = "NO_TEXT_GRIDS"
        return rec
    if not explicit and not dims:
        rec["bucket"] = "NOT_A_PLAN"
        return rec

    try:
        r = run_deterministic_geometry_pass(pdf_path, page_no)
    except Exception as e:
        rec["bucket"] = "ERROR"
        rec["error"] = f"{type(e).__name__}: {e}"
        return rec
    if r.get("status") != "SUCCESS":
        rec["bucket"] = "ERROR"
        return rec

    nv, nh = len(r["vertical_grids"]), len(r["horizontal_grids"])
    rec.update({"v_grids": nv, "h_grids": nh,
                "ppf": r["scale"]["points_per_foot"],
                "scale_explicit": r["scale"]["is_explicit"]})

    bays = [b for k in ("horizontal_dimension_tracks", "vertical_dimension_tracks")
            for t in r[k] for b in t["bays"]]
    matched = [b for b in bays if b.get("ocr_text")]
    errs = []
    for b in matched:
        printed = parse_dimension_string(b["ocr_text"])
        if printed:
            errs.append(abs(b["length_inches"] / 12.0 - printed) * 12.0)
    rec.update({"bays": len(bays), "matched": len(matched),
                "median_err_in": round(statistics.median(errs), 2) if errs else None,
                "agree": sum(1 for b in bays if b.get("agrees_with_ocr"))})

    if nv == 0 and nh == 0:
        rec["bucket"] = "NO_TEXT_GRIDS"
    elif not r["scale"]["is_explicit"]:
        rec["bucket"] = "NO_SCALE"
    elif errs and statistics.median(errs) > 12.0:
        rec["bucket"] = "SCALE_WRONG"
    elif not matched:
        rec["bucket"] = "NO_DIMENSIONS"
    elif nv == 0 or nh == 0:
        rec["bucket"] = "GRIDS_ONE_AXIS"
    else:
        rec["bucket"] = "HEALTHY"
    return rec


def run(lo, hi):
    os.makedirs("debug", exist_ok=True)
    pdfs = sorted(glob.glob(os.path.join("uploads", "*.pdf")))
    done = set()
    if os.path.exists(LOG):
        for line in open(LOG, encoding="utf-8"):
            try:
                d = json.loads(line)
                done.add((d["file"], d["page"]))
            except Exception:
                pass
    out = open(LOG, "a", encoding="utf-8")
    for f in pdfs[lo:hi]:
        try:
            doc = fitz.open(f)
            n = len(doc)
            doc.close()
        except Exception:
            continue
        for p in range(min(n, 12)):
            if (os.path.basename(f), p) in done:
                continue
            try:
                rec = classify(f, p)
            except Exception as e:
                rec = {"file": os.path.basename(f), "page": p,
                       "bucket": "ERROR", "error": f"{type(e).__name__}: {e}"}
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(f'{rec["bucket"]:<16} {rec["file"][:34]:<36} p{p}')
    out.close()


def report():
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8")]
    buckets = {}
    for r in rows:
        buckets.setdefault(r["bucket"], []).append(r)
    total = len(rows)
    print(f"\n{total} pages profiled\n")
    print(f'{"bucket":<16}{"pages":>7}{"share":>8}   what it means for the user')
    print("-" * 92)
    meaning = {
        "HEALTHY": "grids + scale + dimensions all agree",
        "SCALE_WRONG": "distances are wrong by a constant factor",
        "NO_SCALE": "distances are a guess -- no scale on the sheet",
        "SCANNED": "raster page: needs the vision pass",
        "NO_TEXT_GRIDS": "no bubble text found (not a plan, or image bubbles)",
        "NOT_A_PLAN": "schedule/detail/notes sheet",
        "NO_DIMENSIONS": "grids found but nothing to verify against",
        "GRIDS_ONE_AXIS": "only one axis resolved",
        "ERROR": "pass raised",
    }
    for b, rs in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        print(f'{b:<16}{len(rs):>7}{100*len(rs)/total:>7.0f}%   {meaning.get(b,"")}')

    for b in ("SCALE_WRONG", "NO_SCALE", "GRIDS_ONE_AXIS"):
        rs = buckets.get(b, [])
        if not rs:
            continue
        print(f"\n{b} detail:")
        for r in rs[:12]:
            print(f'   {r["file"][:34]:<36} p{r["page"]}  ppf={r.get("ppf")}  '
                  f'scale={r.get("scale_str")!r}  median_err={r.get("median_err_in")}"  '
                  f'grids {r.get("v_grids")}/{r.get("h_grids")}')


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        report()
    else:
        lo = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        hi = int(sys.argv[2]) if len(sys.argv) > 2 else 999
        run(lo, hi)
