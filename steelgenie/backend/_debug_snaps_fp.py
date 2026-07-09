import sys, io, fitz, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

doc  = fitz.open('uploads/Structural snaps.pdf')
page = doc[2]
ppf  = bc.scale_to_pts_per_foot(96)
pw, ph = page.rect.width, page.rect.height

ctx, _   = bc.classify_page_context(page)
cands    = bc.extract_diagonals(page, ppf)
scales   = bc.find_scale_annotations(page)
nodes    = bc.extract_structural_nodes(page, ppf) if ctx in bc.NODE_CHECK_CONTEXTS else None
openings = bc.extract_opening_regions(page)
clfd     = bc.classify(cands, ctx, scales, ppf, nodes, openings)
clfd     = bc.enrich_brace_results(clfd, page)

blocks = page.get_text("blocks")
def nearby(cx, cy, r=120):
    out = []
    for b in blocks:
        bx=(b[0]+b[2])/2; by=(b[1]+b[3])/2
        if math.hypot(bx-cx,by-cy)<r:
            t = b[4].strip().replace('\n',' ')[:40]
            if t: out.append(t)
    return out[:4]

print(f"Page size: {pw:.0f} x {ph:.0f} pts  (right edge = {pw:.0f})")
print(f"ctx={ctx}  ppf={ppf:.1f}")
print()

accepted = [c for c in clfd if c['confidence'] in ('HIGH','MEDIUM')]
print(f"{'#':3}  {'conf':6}  {'len_ft':6}  {'ang':4}  {'x1':6} {'y1':6} {'x2':6} {'y2':6}  {'cfg':17}  {'section':18}  nearby-text")
print("-"*130)
for i,c in enumerate(accepted):
    cx=(c['x1']+c['x2'])/2; cy=(c['y1']+c['y2'])/2
    nb = nearby(cx,cy)
    print(f"{i:3}  {c['confidence']:6}  {c['length_ft']:6.1f}  {c['angle_from_h']:4.0f}"
          f"  {c['x1']:6.0f} {c['y1']:6.0f} {c['x2']:6.0f} {c['y2']:6.0f}"
          f"  {str(c.get('config','')):17}  {str(c.get('section_label','')):18}"
          f"  {nb}")

# Also show fractional position (0-1) so we can see which side of the page
print()
print("=== Fractional positions (right-side = x_frac > 0.6) ===")
for i,c in enumerate(accepted):
    x1f = c['x1']/pw; x2f = c['x2']/pw
    y1f = c['y1']/ph; y2f = c['y2']/ph
    if max(x1f,x2f) > 0.55:
        cx=(c['x1']+c['x2'])/2; cy=(c['y1']+c['y2'])/2
        nb = nearby(cx,cy)
        print(f"  #{i}  {c['confidence']}  {c['length_ft']:.1f}ft"
              f"  x=[{x1f:.2f},{x2f:.2f}]  y=[{y1f:.2f},{y2f:.2f}]"
              f"  {c.get('config')}  {c.get('section_label')}  {nb}")

doc.close()
