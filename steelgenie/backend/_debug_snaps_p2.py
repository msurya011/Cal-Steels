import sys, io, fitz
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

doc = fitz.open('uploads/Structural snaps.pdf')
page = doc[2]
ctx, scores = bc.classify_page_context(page)
print(f'Page context: {ctx}')
print(f'Scores: {scores}')
print()

ppf = bc.scale_to_pts_per_foot(96)
cands = bc.extract_diagonals(page, ppf)
scales = bc.find_scale_annotations(page)
nodes = bc.extract_structural_nodes(page, ppf)
clfd = bc.classify(cands, ctx, scales, ppf, nodes)

print(f'Total candidates: {len(cands)}')
print(f'Classified results: {len(clfd)}')
print(f'Structural nodes: {len(nodes)}')
print()
for c in clfd:
    st = c.get('confidence', 'UNK')
    rr = c.get('reject_reason', '')
    lf = c['length_ft']
    ang = c['angle_from_h']
    x1,y1,x2,y2 = c['x1'],c['y1'],c['x2'],c['y2']
    print(f'  {st:8s}  len={lf:.1f}ft  ang={ang:.0f}deg  ({x1:.0f},{y1:.0f})->({x2:.0f},{y2:.0f})  rej={rr}')

doc.close()
