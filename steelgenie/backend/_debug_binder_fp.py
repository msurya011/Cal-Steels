import sys, io, fitz, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

doc = fitz.open('uploads/#Structural binder.pdf')
ppf = bc.scale_to_pts_per_foot(64)

for pg in [7, 11]:
    page = doc[pg]
    ctx, score = bc.classify_page_context(page)
    cands    = bc.extract_diagonals(page, ppf)
    scales   = bc.find_scale_annotations(page)
    nodes    = bc.extract_structural_nodes(page, ppf)
    openings = bc.extract_opening_regions(page)
    print(f"  openings found: {openings}")
    clfd   = bc.classify(cands, ctx, scales, ppf, nodes, openings)
    blocks = page.get_text("blocks")

    def nearby_text(cx, cy, r=120):
        out = []
        for b in blocks:
            bx=(b[0]+b[2])/2; by=(b[1]+b[3])/2
            if math.hypot(bx-cx,by-cy)<r:
                out.append(b[4].strip().replace('\n',' ')[:50])
        return out

    # Also capture line width per candidate
    # Build map from (x1,y1,x2,y2) -> width
    width_map = {}
    for d in page.get_drawings():
        w = d.get("width", 0)
        for it in d.get("items", []):
            if it[0] == "l":
                key = (round(it[1].x,1), round(it[1].y,1), round(it[2].x,1), round(it[2].y,1))
                width_map[key] = w

    accepted = [c for c in clfd if c['confidence'] in ('HIGH','MEDIUM')]
    print(f"\n=== binder p{pg:02d}  ctx={ctx}  accepted={len(accepted)} ===")
    for c in accepted:
        cx=(c['x1']+c['x2'])/2; cy=(c['y1']+c['y2'])/2
        nb = nearby_text(cx,cy)
        key = (round(c['x1'],1),round(c['y1'],1),round(c['x2'],1),round(c['y2'],1))
        lw  = width_map.get(key, width_map.get((round(c['x2'],1),round(c['y2'],1),round(c['x1'],1),round(c['y1'],1)), -1))
        print(f"  {c['confidence']:6s}  {c['length_ft']:.1f}ft  ang={c['angle_from_h']:.0f}  lw={lw:.3f}  center=({cx:.0f},{cy:.0f})")
        if nb:
            print(f"    text: {nb[:5]}")

doc.close()
