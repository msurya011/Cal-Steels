import sys, io, fitz, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

doc  = fitz.open('uploads/#Structural binder.pdf')
page = doc[7]
ppf  = bc.scale_to_pts_per_foot(64)   # binder uses 64:1

ctx, score = bc.classify_page_context(page)
cands  = bc.extract_diagonals(page, ppf)
scales = bc.find_scale_annotations(page)
nodes  = bc.extract_structural_nodes(page, ppf)
clfd   = bc.classify(cands, ctx, scales, ppf, nodes)

blocks = page.get_text("blocks")

def nearby_text(cx, cy, r=80):
    out = []
    for b in blocks:
        bx = (b[0]+b[2])/2;  by = (b[1]+b[3])/2
        if math.hypot(bx-cx, by-cy) < r:
            out.append(b[4].strip().replace('\n',' ')[:40])
    return out

print(f"ctx={ctx}  score={score}  nodes={len(nodes)}")
print()
accepted = [c for c in clfd if c['confidence'] in ('HIGH','MEDIUM')]
rejected = [c for c in clfd if c['confidence'] == 'REJECT' and c.get('reject_reason') in ('no_structural_node','annotation_xpair')]
print(f"Accepted: {len(accepted)}  (new rejects: {len(rejected)})")
print()

for c in accepted:
    cx = (c['x1']+c['x2'])/2;  cy = (c['y1']+c['y2'])/2
    nb = nearby_text(cx, cy, 100)
    print(f"  {c['confidence']:6s}  {c['length_ft']:.1f}ft  ang={c['angle_from_h']:.0f}  center=({cx:.0f},{cy:.0f})")
    if nb:
        print(f"    text: {nb[:4]}")

# Also check line weights of the detected candidates
print()
print("=== LINE WEIGHTS of accepted candidates ===")
# Re-extract to capture line width
for d in page.get_drawings():
    for item in d.get("items", []):
        if item[0] != "l":
            continue
        p1, p2 = item[1], item[2]
        dx, dy = p2.x - p1.x, p2.y - p1.y
        lng = math.hypot(dx, dy)
        if lng < 5:
            continue
        ang = abs(math.degrees(math.atan2(abs(dy), abs(dx))))
        ang_from_h = min(ang, 90-ang) if ang <= 90 else min(180-ang, ang-90)
        if 20 <= ang_from_h <= 70 and lng >= 5:
            w = d.get("width", -1)
            lf = lng / ppf
            if 7 <= lf <= 30:
                print(f"  width={w:.3f}  len={lf:.1f}ft  ang={ang_from_h:.0f}")

doc.close()
