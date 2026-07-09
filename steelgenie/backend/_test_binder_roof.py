import sys, io, fitz, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

doc = fitz.open('uploads/#Structural binder.pdf')
ppf = bc.scale_to_pts_per_foot(64)
print("Binder PDF — all pages, roof_plan context (node check active):")
for pg in range(len(doc)):
    page = doc[pg]
    cands = bc.extract_diagonals(page, ppf)
    ctx, _ = bc.classify_page_context(page)
    if ctx != 'roof_plan':
        continue
    scales = bc.find_scale_annotations(page)
    nodes = bc.extract_structural_nodes(page, ppf)
    clfd = bc.classify(cands, ctx, scales, ppf, nodes)
    h   = sum(1 for c in clfd if c['confidence'] == 'HIGH')
    m   = sum(1 for c in clfd if c['confidence'] == 'MEDIUM')
    rej = sum(1 for c in clfd if c.get('reject_reason') == 'no_structural_node')
    nn  = len(nodes)
    print(f"  p{pg:02d}  nodes={nn:<4}  H={h}  M={m}  rej_node={rej}")
doc.close()
