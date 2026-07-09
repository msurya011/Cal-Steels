import sys, io, fitz, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

# Test: what happens if we apply node check to braced_frame_elevation pages?
# This tests whether real braces are kept and FPs (annotation symbols) are removed.

tests = [
    ('Structural snaps.pdf', 2, 96, 'snaps p2 (Level 2 Framing Plan - braced_frame_elevation ctx)'),
    ('07_STRUCTURAL_COMBINED.pdf', 51, 192, '07comb p51 (DHM Framing Elevation)'),
    ('07_STRUCTURAL_COMBINED.pdf', 62, 192, '07comb p62 (braced_frame_elevation)'),
    ('07_STRUCTURAL_COMBINED.pdf', 50, 192, '07comb p50 (braced_frame_elevation)'),
]

print("=" * 70)
print("  NODE CHECK on braced_frame_elevation — safety test")
print("  'Before' = without node check  'After' = with node check")
print("=" * 70)

for pdf, pg, scale, label in tests:
    path = f'uploads/{pdf}'
    if not os.path.exists(path):
        print(f'\n  [SKIP] {pdf}')
        continue
    doc = fitz.open(path)
    if pg >= len(doc):
        doc.close()
        continue
    page = doc[pg]
    ppf  = bc.scale_to_pts_per_foot(scale)
    cands = bc.extract_diagonals(page, ppf)
    ctx, _ = bc.classify_page_context(page)
    scales = bc.find_scale_annotations(page)

    # Without node check (current behaviour)
    clfd_before = bc.classify(cands, ctx, scales, ppf, None)
    h_b = sum(1 for c in clfd_before if c['confidence'] == 'HIGH')
    m_b = sum(1 for c in clfd_before if c['confidence'] == 'MEDIUM')

    # With node check forced
    nodes = bc.extract_structural_nodes(page, ppf)
    clfd_after = bc.classify(cands, ctx, scales, ppf, nodes)
    h_a = sum(1 for c in clfd_after if c['confidence'] == 'HIGH')
    m_a = sum(1 for c in clfd_after if c['confidence'] == 'MEDIUM')
    rej = sum(1 for c in clfd_after if c.get('reject_reason') == 'no_structural_node')

    print(f'\n  {label}')
    print(f'  ctx={ctx}  nodes={len(nodes)}')
    print(f'  Before: H={h_b} M={m_b}  total={h_b+m_b}')
    print(f'  After : H={h_a} M={m_a}  total={h_a+m_a}  rej_node={rej}')
    if rej > 0:
        print('  Rejected candidates:')
        for c in clfd_after:
            if c.get('reject_reason') == 'no_structural_node':
                print(f'    len={c["length_ft"]:.1f}ft  ang={c["angle_from_h"]:.0f}deg')
    doc.close()

print()
print("=" * 70)
