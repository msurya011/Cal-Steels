import fitz
import sys
import os
sys.path.insert(0, 'backend')
from app.engineering.grid_geometry_pass import (
    _find_confirmed_bubbles, _build_axis_tracks, _collect_dim_spans,
    detect_scale_factor, _label_rank, _densest_band, _largest_contiguous_run
)

def test_flexible_geometry(pdf_path, page_num):
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    pw, ph = page.rect.width, page.rect.height
    td = page.get_text("dict")
    confirmed = _find_confirmed_bubbles(page, td)
    
    # Try both orientations for numbers
    num_h = _build_axis_tracks(confirmed, "number", pw, ph, band_key="cy", pos_key="cx")
    num_v = _build_axis_tracks(confirmed, "number", pw, ph, band_key="cx", pos_key="cy")
    
    # Try both orientations for letters
    let_h = _build_axis_tracks(confirmed, "letter", pw, ph, band_key="cy", pos_key="cx")
    let_v = _build_axis_tracks(confirmed, "letter", pw, ph, band_key="cx", pos_key="cy")
    
    print("Num H tracks count:", len(num_h), "Num V tracks count:", len(num_v))
    print("Let H tracks count:", len(let_h), "Let V tracks count:", len(let_v))
    
    if num_h:
        for t in num_h:
            print("  Num H track:", t[1], [g['label'] for g in t[0]])
    if num_v:
        for t in num_v:
            print("  Num V track:", t[1], [g['label'] for g in t[0]])
    if let_h:
        for t in let_h:
            print("  Let H track:", t[1], [g['label'] for g in t[0]])
    if let_v:
        for t in let_v:
            print("  Let V track:", t[1], [g['label'] for g in t[0]])

pdf = r'uploads\projects\b52ef5d6-04ac-4497-8793-de6902d5c06a\drawings\4f47d55c-2762-4242-9e40-29ad3e3f182e.pdf'
test_flexible_geometry(pdf, 14)
