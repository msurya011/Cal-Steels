import sys, io, fitz, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

doc = fitz.open('uploads/Structural snaps.pdf')
page = doc[2]
ppf = bc.scale_to_pts_per_foot(96)

cands  = bc.extract_diagonals(page, ppf)
ctx, _ = bc.classify_page_context(page)
scales = bc.find_scale_annotations(page)
nodes  = bc.extract_structural_nodes(page, ppf)
clfd   = bc.classify(cands, ctx, scales, ppf, nodes)

# Get all text blocks with position
blocks = page.get_text("blocks")

def nearby_text(cx, cy, radius=80):
    results = []
    for b in blocks:
        bx = (b[0] + b[2]) / 2
        by = (b[1] + b[3]) / 2
        if math.hypot(bx - cx, by - cy) < radius:
            txt = b[4].strip().replace('\n', ' ')[:40]
            results.append(txt)
    return results

# Also find annotation circles (paths that are roughly circular)
circles = []
for path in page.get_drawings():
    items = path.get("items", [])
    n_c = sum(1 for it in items if it[0] == "c")
    if n_c < 2:
        continue
    r = path.get("rect")
    if not r:
        continue
    w, h = r[2]-r[0], r[3]-r[1]
    if w <= 0 or h <= 0:
        continue
    asp = min(w,h)/max(w,h)
    if asp > 0.65 and 8 < w < 120:
        circles.append((r[0], r[1], r[2], r[3]))

print(f"Context: {ctx}   Annotation circles found: {len(circles)}")
print()

print("=== ACCEPTED CANDIDATES (HIGH / MEDIUM) ===")
for c in clfd:
    if c['confidence'] not in ('HIGH', 'MEDIUM'):
        continue
    x1,y1,x2,y2 = c['x1'],c['y1'],c['x2'],c['y2']
    cx, cy = (x1+x2)/2, (y1+y2)/2
    nearby = nearby_text(cx, cy, 100)
    # Check if center near any annotation circle
    in_circle = any(r0 <= cx <= r2 and r1 <= cy <= r3 for r0,r1,r2,r3 in circles)
    print(f"  {c['confidence']:6s}  {c['length_ft']:.1f}ft  ang={c['angle_from_h']:.0f}  center=({cx:.0f},{cy:.0f})  in_circle={in_circle}")
    if nearby:
        print(f"    nearby text: {nearby[:4]}")
    print()

doc.close()
