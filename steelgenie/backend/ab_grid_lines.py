"""
A/B the line-to-line measurement against the old bubble-centre measurement.

For each sheet, runs the deterministic pass twice -- once with
GRID_USE_LINE_GEOMETRY=0 (baseline) and once with it on -- and compares each
bay against the printed dimension string that the sheet itself carries. The
printed string is independent ground truth: it was written by the engineer,
not derived from either measurement.

The number that matters is the agreement rate. If measuring line-to-line is
the correct thing to do, more bays should land within tolerance of what the
drawing says, and the mean absolute error against the printed dimensions
should fall.

    python ab_grid_lines.py [n_sheets]
"""

import sys
import os
import glob
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz


def collect(pdf_path, page_no):
    """Re-import the module under the current env flag, then run one page."""
    import app.engineering.grid_line_geometry as glg
    import app.engineering.grid_geometry_pass as ggp
    importlib.reload(glg)
    importlib.reload(ggp)
    try:
        r = ggp.run_deterministic_geometry_pass(pdf_path, page_no)
    except Exception:
        return None
    if r.get("status") != "SUCCESS":
        return None

    ppf = r["scale"]["points_per_foot"]
    rows = {}
    for key in ("horizontal_dimension_tracks", "vertical_dimension_tracks"):
        for t in r.get(key, []):
            for b in t.get("bays", []):
                if not b.get("ocr_text"):
                    continue
                printed = ggp.parse_dimension_string(b["ocr_text"])
                if printed is None:
                    continue
                measured = b["length_inches"] / 12.0
                rows[(key, t.get("side"), b["from_grid"], b["to_grid"])] = {
                    "printed_ft": printed,
                    "measured_ft": measured,
                    "err_in": abs(measured - printed) * 12.0,
                }
    return {"rows": rows, "ppf": ppf,
            "src": r.get("grid_line_geometry", {}).get("measured_between"),
            "rejected": r.get("grid_line_geometry", {}).get("outliers_rejected")}


def summarise(rows, tol_in=1.5):
    if not rows:
        return None
    errs = [v["err_in"] for v in rows.values()]
    within = [e for e in errs if e <= tol_in]
    return {
        "bays": len(errs),
        "within_tol": len(within),
        "pct": round(100.0 * len(within) / len(errs), 1),
        "mean_err_in": round(sum(errs) / len(errs), 2),
        "median_err_in": round(sorted(errs)[len(errs) // 2], 2),
    }


def run_sheet(pdf_path, max_pages=6):
    doc = fitz.open(pdf_path)
    n = min(len(doc), max_pages)
    doc.close()

    agg = {"off": {}, "on": {}}
    meta = {}
    for pno in range(n):
        for mode, flag in (("off", "0"), ("on", "1")):
            os.environ["GRID_USE_LINE_GEOMETRY"] = flag
            res = collect(pdf_path, pno)
            if not res:
                continue
            for k, v in res["rows"].items():
                agg[mode][(pno,) + k] = v
            if mode == "on":
                meta[pno] = (res["src"], res["rejected"])

    # Compare only bays BOTH modes produced, so the delta is measurement,
    # not a difference in which bays got detected.
    common = set(agg["off"]) & set(agg["on"])
    if not common:
        return None
    bad_pages = set()
    for pno in {k[0] for k in common}:
        errs = sorted(agg["off"][k]["err_in"] for k in common if k[0] == pno)
        if errs and errs[len(errs) // 2] > 12.0:
            bad_pages.add(pno)
    if bad_pages:
        common = {k for k in common if k[0] not in bad_pages}
        print(f'  [note] {os.path.basename(pdf_path)}: skipped page(s) '
              f'{sorted(bad_pages)} -- baseline median error > 12", scale not calibrated')
    if not common:
        return None
    off = summarise({k: agg["off"][k] for k in common})
    on = summarise({k: agg["on"][k] for k in common})

    improved = sum(1 for k in common if agg["on"][k]["err_in"] < agg["off"][k]["err_in"] - 0.05)
    worsened = sum(1 for k in common if agg["on"][k]["err_in"] > agg["off"][k]["err_in"] + 0.05)

    return {"file": os.path.basename(pdf_path), "compared_bays": len(common),
            "baseline_bubble_centres": off, "line_to_line": on,
            "bays_improved": improved, "bays_worsened": worsened, "meta": meta}


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and not args[0].isdigit():
        pdfs = args
    else:
        n = int(args[0]) if args else 5
        pdfs = sorted(glob.glob(os.path.join("uploads", "*.pdf")))[:n]

    totals = {"cmp": 0, "imp": 0, "wor": 0, "off_ok": 0, "on_ok": 0,
              "off_err": 0.0, "on_err": 0.0}

    for p in pdfs:
        try:
            res = run_sheet(p)
        except Exception as e:
            print(f"[skip] {os.path.basename(p)}: {type(e).__name__}: {e}")
            continue
        if not res:
            print(f"[----] {os.path.basename(p)}: no comparable bays")
            continue
        b, l = res["baseline_bubble_centres"], res["line_to_line"]
        print(f'\n{res["file"]}')
        print(f'  bays compared      : {res["compared_bays"]}')
        print(f'  bubble centres     : {b["within_tol"]}/{b["bays"]} within 1.5"  '
              f'({b["pct"]}%)  mean err {b["mean_err_in"]}"  median {b["median_err_in"]}"')
        print(f'  line to line       : {l["within_tol"]}/{l["bays"]} within 1.5"  '
              f'({l["pct"]}%)  mean err {l["mean_err_in"]}"  median {l["median_err_in"]}"')
        print(f'  improved / worsened: {res["bays_improved"]} / {res["bays_worsened"]}')
        totals["cmp"] += res["compared_bays"]
        totals["imp"] += res["bays_improved"]
        totals["wor"] += res["bays_worsened"]
        totals["off_ok"] += b["within_tol"]
        totals["on_ok"] += l["within_tol"]
        totals["off_err"] += b["mean_err_in"] * b["bays"]
        totals["on_err"] += l["mean_err_in"] * l["bays"]

    if totals["cmp"]:
        print("\n" + "=" * 70)
        print(f'TOTAL over {totals["cmp"]} bays')
        print(f'  bubble centres : {totals["off_ok"]} within tol  '
              f'(mean err {totals["off_err"]/totals["cmp"]:.2f}")')
        print(f'  line to line   : {totals["on_ok"]} within tol  '
              f'(mean err {totals["on_err"]/totals["cmp"]:.2f}")')
        print(f'  improved {totals["imp"]}  /  worsened {totals["wor"]}')
