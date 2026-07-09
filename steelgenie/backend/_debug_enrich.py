import sys, io, fitz, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

tests = [
    ("uploads/#Structural binder.pdf",         7,  64),
    ("uploads/#Structural binder.pdf",         11,  64),
    ("uploads/Structural snaps.pdf",            2,  96),
    ("uploads/2026.03.27_Bayhealth Sussex MOB_DD Set_Structural.pdf", 5, 96),
    ("uploads/02 Struct 98 Spruce_2026-03-13_BID.pdf", 3, 96),
]

for path, pg, scale in tests:
    doc  = fitz.open(path)
    page = doc[pg]
    ppf  = bc.scale_to_pts_per_foot(scale)
    ctx, _ = bc.classify_page_context(page)
    cands  = bc.extract_diagonals(page, ppf)
    scales = bc.find_scale_annotations(page)
    nodes  = bc.extract_structural_nodes(page, ppf) if ctx in bc.NODE_CHECK_CONTEXTS else None
    openings = bc.extract_opening_regions(page)
    clfd   = bc.classify(cands, ctx, scales, ppf, nodes, openings)
    clfd   = bc.enrich_brace_results(clfd, page)

    accepted = [c for c in clfd if c['confidence'] in ('HIGH','MEDIUM')]
    name = path.replace('uploads/','')[:40]
    print(f"\n=== {name}  p{pg:02d}  ctx={ctx}  ({len(accepted)} accepted) ===")
    for c in accepted:
        print(f"  {c['confidence']:6s}  {c['length_ft']:5.1f}ft"
              f"  cfg={c['config']:17s}"
              f"  section={str(c['section_label']):18s}"
              f"  role={c['role']}")
    doc.close()
