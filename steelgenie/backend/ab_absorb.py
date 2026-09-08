"""
A/B the interior-grid absorption across the whole corpus.

The question this answers: does recovering grids from interior rails find REAL
grids, or does it admit noise?

The score is agreement between the geometry and the sheets' own printed
dimension strings. A recovered grid that is real subdivides a bay into pieces
the drawing also dimensions, so agreement should hold or rise. A recovered
grid that is noise inserts a boundary the drawing never dimensions, so
agreement should fall and unmatched bays should climb.

Reported per sheet and in total:
  grids      -- how many grids the pass produced
  matched    -- bays that found a printed dimension to compare against
  agree      -- of those, how many agreed within tolerance
  orphans    -- bays with no printed dimension anywhere near them (the
                signature of a fabricated grid boundary)

    python ab_absorb.py
"""

import os
import sys
import glob
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz


def score(pdf_path, page_no):
    import app.engineering.grid_geometry_pass as ggp
    importlib.reload(ggp)
    try:
        r = ggp.run_deterministic_geometry_pass(pdf_path, page_no)
    except Exception:
        return None
    if r.get("status") != "SUCCESS":
        return None

    grids = len(r["vertical_grids"]) + len(r["horizontal_grids"])
    if not grids:
        return None

    bays = [b for k in ("horizontal_dimension_tracks", "vertical_dimension_tracks")
            for t in r[k] for b in t["bays"]]
    matched = [b for b in bays if b["agrees_with_ocr"] is not None]
    agree = [b for b in matched if b["agrees_with_ocr"]]
    orphans = [b for b in bays if b["agrees_with_ocr"] is None]
    recovered = ((r["vertical_axis_meta"].get("interior_grids_recovered") or [])
                 + (r["horizontal_axis_meta"].get("interior_grids_recovered") or []))
    return {"grids": grids, "bays": len(bays), "matched": len(matched),
            "agree": len(agree), "orphans": len(orphans), "recovered": recovered}


def main():
    tot = {"on": dict(grids=0, matched=0, agree=0, orphans=0, bays=0),
           "off": dict(grids=0, matched=0, agree=0, orphans=0, bays=0)}
    recovered_all = []
    rows = []

    for f in sorted(glob.glob(os.path.join("uploads", "*.pdf"))):
        try:
            d = fitz.open(f)
            n = min(len(d), 5)
            d.close()
        except Exception:
            continue
        for p in range(n):
            res = {}
            for mode, flag in (("off", "0"), ("on", "1")):
                os.environ["GRID_ABSORB_INTERIOR"] = flag
                res[mode] = score(f, p)
            if not res["on"] or not res["off"]:
                continue
            if not res["on"]["recovered"]:
                # Nothing changed on this page; count it but don't print it.
                for m in ("on", "off"):
                    for k in tot[m]:
                        tot[m][k] += res[m][k]
                continue
            recovered_all += res["on"]["recovered"]
            rows.append((os.path.basename(f)[:34], p, res["off"], res["on"]))
            for m in ("on", "off"):
                for k in tot[m]:
                    tot[m][k] += res[m][k]

    print(f'{"sheet":<36}{"pg":>3} | {"grids":>11} | {"agree/matched":>15} | {"orphan bays":>12}')
    print("-" * 88)
    for name, p, off, on in rows:
        print(f'{name:<36}{p:>3} | {off["grids"]:>4} -> {on["grids"]:<4} | '
              f'{off["agree"]}/{off["matched"]} -> {on["agree"]}/{on["matched"]:<6} | '
              f'{off["orphans"]:>4} -> {on["orphans"]:<4}')
        print(f'{"":<39}   recovered: {on["recovered"]}')

    print("\n" + "=" * 88)
    for m, label in (("off", "absorption OFF"), ("on", "absorption ON ")):
        t = tot[m]
        pct = 100.0 * t["agree"] / t["matched"] if t["matched"] else 0.0
        orph = 100.0 * t["orphans"] / t["bays"] if t["bays"] else 0.0
        print(f'{label}: {t["grids"]:>4} grids  '
              f'agreement {t["agree"]:>4}/{t["matched"]:<4} ({pct:5.1f}%)  '
              f'orphan bays {t["orphans"]:>4}/{t["bays"]:<4} ({orph:5.1f}%)')
    print(f'\ngrids recovered in total: {len(recovered_all)}')


if __name__ == "__main__":
    main()
