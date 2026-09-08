"""
Verify the line-vs-bubble change on real sheets.

Runs the deterministic geometry pass over a PDF, and for every page that
produced grids reports:

  * how many grid coordinates came from a real chain line vs. the old
    bubble-centre fallback,
  * the worst bubble-to-line offsets, in inches, so the error the previous
    measurement was absorbing is visible as a number,
  * every bay where the line-to-line span and the old bubble-centre span
    disagree by more than 1",
  * OCR agreement: bay lengths measured off the geometry against the printed
    dimension strings on the sheet, before and after the change.

Usage:
    python verify_grid_lines.py <sheet.pdf> [page ...]
    python verify_grid_lines.py --sweep      # first N sheets in uploads/
"""

import sys
import os
import json
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from app.engineering.grid_geometry_pass import run_deterministic_geometry_pass


def inches(pts, ppf):
    return None if not ppf else round(pts / ppf * 12.0, 2)


def report_page(pdf_path, page_no):
    try:
        r = run_deterministic_geometry_pass(pdf_path, page_no)
    except Exception as e:
        return {"page": page_no, "error": f"{type(e).__name__}: {e}"}

    if r.get("status") != "SUCCESS":
        return {"page": page_no, "error": r.get("status")}

    v = r.get("vertical_grids") or []
    h = r.get("horizontal_grids") or []
    if not v and not h:
        return None

    glg = r.get("grid_line_geometry", {})
    ppf = r["scale"]["points_per_foot"]

    # Bays where the fix actually moved the number.
    moved = []
    all_bays = []
    for track_key in ("horizontal_dimension_tracks", "vertical_dimension_tracks"):
        for t in r.get(track_key, []):
            for b in t.get("bays", []):
                all_bays.append(b)
                d = b.get("bubble_centre_delta_inches")
                if d is not None and abs(d) >= 1.0:
                    moved.append({
                        "side": t.get("side"),
                        "bay": f'{b["from_grid"]}->{b["to_grid"]}',
                        "line_to_line": b["dimension_text"],
                        "was_bubble_centre_off_by_in": d,
                        "measured_between": b.get("measured_between"),
                        "ocr": b.get("ocr_text"),
                        "agrees": b.get("agrees_with_ocr"),
                    })

    matched = [b for b in all_bays if b.get("agrees_with_ocr") is not None]
    agreeing = [b for b in matched if b["agrees_with_ocr"]]

    return {
        "page": page_no,
        "title_scale": r["scale"]["scale_string"],
        "pts_per_foot": ppf,
        "grids": {"vertical": len(v), "horizontal": len(h)},
        "coord_source": glg.get("measured_between"),
        "line_confirmed": f'{glg.get("vertical_line_confirmed")}/{glg.get("vertical_total")} V, '
                          f'{glg.get("horizontal_line_confirmed")}/{glg.get("horizontal_total")} H',
        "index_stats": glg.get("index_stats"),
        "worst_offsets_v": glg.get("worst_vertical_offsets", [])[:4],
        "worst_offsets_h": glg.get("worst_horizontal_offsets", [])[:4],
        "bays_total": len(all_bays),
        "ocr_agreement": (f"{len(agreeing)}/{len(matched)}" if matched else "no OCR matches"),
        "bays_changed_by_fix": moved[:12],
        "bays_changed_count": len(moved),
    }


def run(pdf_path, pages=None):
    doc = fitz.open(pdf_path)
    n = len(doc)
    doc.close()
    todo = pages if pages else range(min(n, 12))

    print("=" * 78)
    print(os.path.basename(pdf_path), f"({n} pages)")
    print("=" * 78)

    any_hit = False
    for pno in todo:
        rep = report_page(pdf_path, pno)
        if rep is None:
            continue
        any_hit = True
        print(json.dumps(rep, indent=2, default=str))
        print("-" * 78)
    if not any_hit:
        print("  no pages with confirmed grids")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--sweep":
        for p in sorted(glob.glob(os.path.join("uploads", "*.pdf")))[:6]:
            run(p)
    elif args:
        pages = [int(a) for a in args[1:]] or None
        run(args[0], pages)
    else:
        print(__doc__)
