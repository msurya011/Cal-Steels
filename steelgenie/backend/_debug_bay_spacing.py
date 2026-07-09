import sys, io, fitz, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

doc = fitz.open('uploads/Structural snaps.pdf')
page = doc[2]
ppf  = bc.scale_to_pts_per_foot(96)

min_pt = bc.NODE_MIN_LINE_FT * ppf
hy_vals = []
vx_vals = []

for d in page.get_drawings():
    for item in d.get("items", []):
        if item[0] != "l":
            continue
        p1, p2 = item[1], item[2]
        dx, dy = p2.x - p1.x, p2.y - p1.y
        ln = math.hypot(dx, dy)
        if ln < min_pt:
            continue
        ang   = abs(math.degrees(math.atan2(dy, dx))) % 180
        ang_h = min(ang, 180 - ang)
        if ang_h <= 10:
            hy_vals.append((p1.y + p2.y) / 2)
        elif ang_h >= 80:
            vx_vals.append((p1.x + p2.x) / 2)

def sorted_spacings(vals, snap=20):
    buckets = sorted(set(round(v / snap) * snap for v in vals))
    if len(buckets) < 2:
        return []
    return [buckets[i+1] - buckets[i] for i in range(len(buckets)-1)]

h_spacings = sorted_spacings(hy_vals)
v_spacings = sorted_spacings(vx_vals)

print(f"H-lines found: {len(hy_vals)}  unique bucketed: {len(set(round(v/20)*20 for v in hy_vals))}")
print(f"V-lines found: {len(vx_vals)}  unique bucketed: {len(set(round(v/20)*20 for v in vx_vals))}")
print()
print(f"H-line spacings (pts): {sorted(h_spacings)[:10]}")
print(f"V-line spacings (pts): {sorted(v_spacings)[:10]}")
print()
print(f"Min H spacing: {min(h_spacings) if h_spacings else 0:.1f} pts = {min(h_spacings)/ppf if h_spacings else 0:.1f} ft")
print(f"Min V spacing: {min(v_spacings) if v_spacings else 0:.1f} pts = {min(v_spacings)/ppf if v_spacings else 0:.1f} ft")
print()
print(f"Annotation X bounding box: 60 x 47 pts = {60/ppf:.1f} x {47/ppf:.1f} ft")
print(f"Min bay (pts): {min(min(h_spacings or [999]), min(v_spacings or [999])):.1f}")

doc.close()
