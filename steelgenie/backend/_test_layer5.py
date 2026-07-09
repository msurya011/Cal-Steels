"""
Layer 5 targeted test:
1. Find pages where opening zones AND brace candidates co-exist (opening FP test)
2. Find roof pages with remaining MEDIUM braces (spatial not catching all)
3. Compare HIGH/MEDIUM counts before vs after Layer 5 changes
"""
import sys, io, fitz, os, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc
from collections import Counter

PDFS = [
    ('STRUCTURAL 5-26-26.pdf',   96),
    ('#Structural binder.pdf',   64),
    ('Structural snaps.pdf',     96),
    ('07_STRUCTURAL_COMBINED.pdf', 192),
    ('2026.03.27_Bayhealth Sussex MOB_DD Set_Structural.pdf', 192),
    ('02 Struct 98 Spruce_2026-03-13_BID.pdf', 96),
]

print("=== PAGES WITH 'OPEN TO BELOW' TEXT + brace candidates ===\n")
for pdf, scale in PDFS:
    path = f'uploads/{pdf}'
    if not os.path.exists(path): continue
    doc = fitz.open(path)
    ppf = bc.scale_to_pts_per_foot(scale)
    for pg in range(len(doc)):
        try:
            page  = doc[pg]
            zones = bc.extract_opening_zones(page)
            if not zones: continue
            cands = bc.extract_diagonals(page, ppf)
            if not cands: continue
            ctx, _ = bc.classify_page_context(page)
            clfd   = bc.classify(cands, ctx, None, ppf, zones)
            h = sum(1 for c in clfd if c['confidence'] == 'HIGH')
            m = sum(1 for c in clfd if c['confidence'] == 'MEDIUM')
            og = sum(1 for c in clfd if c.get('reject_reason') == 'opening_geometry')
            if h + m > 0:
                # Check if any MEDIUM/HIGH are within 600pt of a zone (potential FP)
                close_to_zone = 0
                for c in clfd:
                    if c['confidence'] not in ('HIGH', 'MEDIUM'): continue
                    mx = (c['x1'] + c['x2']) / 2
                    my = (c['y1'] + c['y2']) / 2
                    for (zx, zy) in zones:
                        if math.hypot(mx - zx, my - zy) < 500:
                            close_to_zone += 1
                            break
                print(f'  {pdf[:35]} p{pg}: ctx={ctx}  zones={len(zones)}'
                      f'  H={h} M={m}  opening_rej={og}  close_to_zone={close_to_zone}')
        except Exception:
            pass
    doc.close()

print("\n=== ROOF PLANS WITH REMAINING MEDIUM BRACES (potential FPs) ===\n")
for pdf, scale in PDFS:
    path = f'uploads/{pdf}'
    if not os.path.exists(path): continue
    doc = fitz.open(path)
    ppf = bc.scale_to_pts_per_foot(scale)
    for pg in range(len(doc)):
        try:
            page  = doc[pg]
            ctx, _ = bc.classify_page_context(page)
            if ctx not in ('roof_plan', 'unknown'): continue
            t = page.get_text('text')[:800].upper()
            if 'ROOF' not in t: continue
            cands  = bc.extract_diagonals(page, ppf)
            zones  = bc.extract_opening_zones(page)
            clfd   = bc.classify(cands, ctx, None, ppf, zones)
            h  = sum(1 for c in clfd if c['confidence'] == 'HIGH')
            m  = sum(1 for c in clfd if c['confidence'] == 'MEDIUM')
            sp = sum(1 for c in clfd if c.get('reject_reason') == 'spatial_cluster')
            if h + m > 0:
                print(f'  {pdf[:35]} p{pg}: ctx={ctx}  H={h} M={m}  spatial_rej={sp}  cands={len(cands)}')
        except Exception:
            pass
    doc.close()

print("\n=== VALIDATION: key pages braced-frame elevations preserved ===\n")
kept = [
    ('#Structural binder.pdf',                   12, 64,  'binder framing p12'),
    ('Structural snaps.pdf',                       5,  96, 'snaps elevation p5'),
    ('Structural snaps.pdf',                       6,  96, 'snaps elevation p6'),
    ('02 Struct 98 Spruce_2026-03-13_BID.pdf',    2,  96, 'spruce framing p2'),
]
for pdf, pg, scale, label in kept:
    path = f'uploads/{pdf}'
    if not os.path.exists(path): continue
    doc = fitz.open(path)
    if pg >= len(doc):
        doc.close()
        continue
    page  = doc[pg]
    ppf   = bc.scale_to_pts_per_foot(scale)
    cands = bc.extract_diagonals(page, ppf)
    ctx, _ = bc.classify_page_context(page)
    zones  = bc.extract_opening_zones(page)
    clfd   = bc.classify(cands, ctx, None, ppf, zones)
    h = sum(1 for c in clfd if c['confidence'] == 'HIGH')
    m = sum(1 for c in clfd if c['confidence'] == 'MEDIUM')
    print(f'  {label}: ctx={ctx}  H={h} M={m}  (should be >0)')
    doc.close()
