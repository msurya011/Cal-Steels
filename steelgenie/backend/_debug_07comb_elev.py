import sys, io, fitz
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

doc = fitz.open('uploads/07_STRUCTURAL_COMBINED.pdf')
ppf = bc.scale_to_pts_per_foot(192)

for pg in [47, 48]:
    page = doc[pg]
    ctx, score = bc.classify_page_context(page)
    cands = bc.extract_diagonals(page, ppf)
    scales = bc.find_scale_annotations(page)
    nodes = bc.extract_structural_nodes(page, ppf)
    clfd = bc.classify(cands, ctx, scales, ppf, nodes)

    accepted = [c for c in clfd if c['confidence'] in ('HIGH','MEDIUM')]
    print(f"\n=== 07comb p{pg}  ctx={ctx}  score={score} ===")
    print(f"  Accepted braces: {len(accepted)}")
    for c in accepted:
        print(f"  {c['confidence']:6s}  len={c['length_ft']:.1f}ft  ang={c['angle_from_h']:.0f}deg")

doc.close()
