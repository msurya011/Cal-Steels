import sys, io, fitz, os, inspect
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

sig    = inspect.signature(bc.classify)
params = list(sig.parameters.keys())
print('classify() params:', params)

for name in ['extract_opening_zones', 'find_spatial_clusters', 'is_opening_marker',
             '_candidate_category']:
    status = 'STILL PRESENT - revert incomplete' if hasattr(bc, name) else 'removed OK'
    print(f'  {name}: {status}')

# Smoke test on the known elevation page
path = 'uploads/Structural snaps.pdf'
if os.path.exists(path):
    doc   = fitz.open(path)
    page  = doc[7]
    ppf   = bc.scale_to_pts_per_foot(96)
    cands = bc.extract_diagonals(page, ppf)
    ctx, _ = bc.classify_page_context(page)
    clfd  = bc.classify(cands, ctx, None, ppf)
    h = sum(1 for c in clfd if c['confidence'] == 'HIGH')
    m = sum(1 for c in clfd if c['confidence'] == 'MEDIUM')
    print(f'Smoke test snaps p7: ctx={ctx}  H={h} M={m}  (expect braced_frame_elevation / H=9)')
    doc.close()
