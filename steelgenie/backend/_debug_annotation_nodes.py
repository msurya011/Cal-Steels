import sys, io, fitz, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

doc = fitz.open('uploads/Structural snaps.pdf')
page = doc[2]
ppf = bc.scale_to_pts_per_foot(96)
nodes = bc.extract_structural_nodes(page, ppf)

# The annotation X candidates
annotation = [
    (499, 604, 439, 651, 'ann-1'),
    (499, 651, 439, 604, 'ann-2'),
]

# A real HIGH brace endpoint
real_braces = [
    (620, 761, 934, 1311, 'real-70ft'),
    (2056, 551, 2209, 722, 'real-25.5ft'),
    (1587, 566, 1748, 501, 'real-19ft'),
]

SNAP = bc.NODE_SNAP_PT

def nearest_node(x, y, nodes):
    best = min(nodes, key=lambda n: math.hypot(n[0]-x, n[1]-y))
    return best, math.hypot(best[0]-x, best[1]-y)

print(f"NODE_SNAP_PT = {SNAP}  |  Total nodes = {len(nodes)}")
print()

print("=== ANNOTATION candidates ===")
for x1,y1,x2,y2,label in annotation:
    n1, d1 = nearest_node(x1, y1, nodes)
    n2, d2 = nearest_node(x2, y2, nodes)
    hit1 = d1 < SNAP
    hit2 = d2 < SNAP
    print(f"{label}: ({x1},{y1})->({x2},{y2})")
    print(f"  p1 nearest node: {n1}  dist={d1:.1f}  HIT={hit1}")
    print(f"  p2 nearest node: {n2}  dist={d2:.1f}  HIT={hit2}")
    print(f"  would pass node check: {hit1 or hit2}")
    print()

print("=== REAL BRACE endpoints ===")
for x1,y1,x2,y2,label in real_braces:
    n1, d1 = nearest_node(x1, y1, nodes)
    n2, d2 = nearest_node(x2, y2, nodes)
    hit1 = d1 < SNAP
    hit2 = d2 < SNAP
    print(f"{label}: ({x1},{y1})->({x2},{y2})")
    print(f"  p1 nearest node: {n1}  dist={d1:.1f}  HIT={hit1}")
    print(f"  p2 nearest node: {n2}  dist={d2:.1f}  HIT={hit2}")
    print(f"  would pass node check: {hit1 or hit2}")
    print()

doc.close()
