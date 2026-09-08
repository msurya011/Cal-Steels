"""Dump the candidate chain lines competing for each grid bubble."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from app.engineering.grid_line_geometry import build_line_index, BUBBLE_TO_LINE_TOL_PTS
from app.engineering.grid_geometry_pass import _find_confirmed_bubbles

pdf, pno = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0
doc = fitz.open(pdf); page = doc[pno]
rect = page.rect
pw, ph = (rect.height, rect.width) if page.rotation in (90, 270) else (rect.width, rect.height)
rot = page.rotation_matrix if page.rotation != 0 else None
td = page.get_text("dict")

li = build_line_index(page, pw, ph, rot)
print("index:", li.stats)
print("page displayed:", round(pw,1), "x", round(ph,1))

conf = _find_confirmed_bubbles(page, td, line_index=None)
nums = [c for c in conf if c["axis"] == "number"]
lets = [c for c in conf if c["axis"] == "letter"]
print(f"\nconfirmed bubbles: {len(nums)} numeric, {len(lets)} alpha")

# Which family is on a horizontal rail (labels vertical grid lines)?
def spread(items, k):
    return (max(i[k] for i in items) - min(i[k] for i in items)) if items else 0
print("numeric spread  x=%.0f y=%.0f" % (spread(nums,"cx"), spread(nums,"cy")))
print("alpha   spread  x=%.0f y=%.0f" % (spread(lets,"cx"), spread(lets,"cy")))

target = nums if spread(nums,"cx") > spread(nums,"cy") else lets
print("\n--- vertical-line candidates near each bubble of the horizontal-rail family ---")
for c in sorted(target, key=lambda c: c["cx"])[:10]:
    print(f'\nbubble {c["text"]!r:>6}  cx={c["cx"]:8.2f} cy={c["cy"]:8.2f}')
    cands = [L for L in li.vertical if abs(L["coord"] - c["cx"]) <= 40]
    cands.sort(key=lambda L: abs(L["coord"] - c["cx"]))
    for L in cands[:6]:
        if c["cy"] < L["lo"]:   gap = L["lo"] - c["cy"]
        elif c["cy"] > L["hi"]: gap = c["cy"] - L["hi"]
        else:                   gap = 0.0
        print(f'    dx={L["coord"]-c["cx"]:+7.2f}  extent=[{L["lo"]:7.1f},{L["hi"]:7.1f}] '
              f'len={L["hi"]-L["lo"]:7.1f} ink={L["ink"]:7.1f} segs={L["segments"]:3d} '
              f'dashed={int(L["dashed"])}  end_gap={gap:7.1f}')
doc.close()
