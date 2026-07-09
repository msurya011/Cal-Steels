import sys, io, fitz, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

doc = fitz.open('uploads/#Structural binder.pdf')
page = doc[11]
ppf  = bc.scale_to_pts_per_foot(64)
blocks = page.get_text("blocks")

# Find all text blocks near the two RTU candidates
rtu_centers = [(758, 873), (785, 766)]
print("=== Nearby text (r=300) around RTU candidates ===")
for cx, cy in rtu_centers:
    print(f"\nCandidate center ({cx},{cy}):")
    nearby = sorted(
        [(math.hypot((b[0]+b[2])/2-cx, (b[1]+b[3])/2-cy), b[4].strip().replace('\n',' ')[:60])
         for b in blocks],
        key=lambda x: x[0]
    )[:12]
    for dist, txt in nearby:
        if dist < 300:
            print(f"  d={dist:.0f}  [{txt}]")

# Find all "DECK TYPE" labels on this page
print("\n=== DECK TYPE blocks ===")
for b in blocks:
    if 'DECK' in b[4].upper() and 'TYPE' in b[4].upper():
        cx = (b[0]+b[2])/2; cy = (b[1]+b[3])/2
        print(f"  [{b[4].strip().replace(chr(10),' ')[:40]}]  center=({cx:.0f},{cy:.0f})")

doc.close()
