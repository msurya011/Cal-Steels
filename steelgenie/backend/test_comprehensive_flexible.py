import fitz
import sys
import os
sys.path.insert(0, 'backend')
from app.engineering.grid_geometry_pass import (
    _find_confirmed_bubbles, _build_axis_tracks, _collect_dim_spans,
    detect_scale_factor, _label_rank, _densest_band, _largest_contiguous_run,
    _make_bays, to_frontend_dimension_lines
)

def run_test_pass(pdf_path, page_num, override_ppf=None):
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    pw, ph = page.rect.width, page.rect.height
    td = page.get_text("dict")
    confirmed = _find_confirmed_bubbles(page, td)
    dim_spans = _collect_dim_spans(td)
    pts_per_foot = override_ppf or 9.0

    num_tracks_h = _build_axis_tracks(confirmed, "number", pw, ph, band_key="cy", pos_key="cx", edge=0.48)
    num_tracks_v = _build_axis_tracks(confirmed, "number", pw, ph, band_key="cx", pos_key="cy", edge=0.48)
    num_h_count = sum(len(t[0]) for t in num_tracks_h)
    num_v_count = sum(len(t[0]) for t in num_tracks_v)

    let_tracks_v = _build_axis_tracks(confirmed, "letter", pw, ph, band_key="cx", pos_key="cy", edge=0.48)
    let_tracks_h = _build_axis_tracks(confirmed, "letter", pw, ph, band_key="cy", pos_key="cx", edge=0.48)
    let_v_count = sum(len(t[0]) for t in let_tracks_v)
    let_h_count = sum(len(t[0]) for t in let_tracks_h)

    if num_h_count >= num_v_count and let_v_count >= let_h_count:
        v_tracks = num_tracks_h
        h_tracks = let_tracks_v
    elif num_v_count > num_h_count and let_h_count >= let_v_count:
        v_tracks = let_tracks_h
        h_tracks = num_tracks_v
    elif num_h_count >= num_v_count:
        v_tracks = num_tracks_h
        h_tracks = let_tracks_v if let_tracks_v else let_tracks_h
    else:
        v_tracks = let_tracks_h if let_tracks_h else let_tracks_v
        h_tracks = num_tracks_v

    print(f"\nResults for {os.path.basename(pdf_path)} (Page {page_num+1}):")
    print(f"  Vertical Grid tracks (X axis): {[t[1]['side'] for t in v_tracks]}")
    for t in v_tracks:
        print(f"    grids: {[g['label'] for g in t[0]]} at band {t[1]['band_coord']}")
        bays = _make_bays(t[0], "V", t[1]['band_coord'], pts_per_foot=pts_per_foot, dim_spans=dim_spans)
        for b in bays:
            print(f"      {b['from_grid']}->{b['to_grid']}: {b['dimension_text']} (ocr: {b.get('ocr_text')})")
            
    print(f"  Horizontal Grid tracks (Y axis): {[t[1]['side'] for t in h_tracks]}")
    for t in h_tracks:
        print(f"    grids: {[g['label'] for g in t[0]]} at band {t[1]['band_coord']}")
        bays = _make_bays(t[0], "H", t[1]['band_coord'], pts_per_foot=pts_per_foot, dim_spans=dim_spans)
        for b in bays:
            print(f"      {b['from_grid']}->{b['to_grid']}: {b['dimension_text']} (ocr: {b.get('ocr_text')})")

pdf_new = r'backend\uploads\projects\b52ef5d6-04ac-4497-8793-de6902d5c06a\drawings\4f47d55c-2762-4242-9e40-29ad3e3f182e.pdf'
pdf_laredo = r'backend\uploads\projects\a7be03fa-a3da-404f-8ee1-38240df8015a\drawings\4041fc0c-59ec-483f-aabc-25168ea718de.pdf'

run_test_pass(pdf_new, 14, override_ppf=864.0/96.0)
run_test_pass(pdf_laredo, 12, override_ppf=864.0/96.0)
