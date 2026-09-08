import fitz
import sys
import os
sys.path.insert(0, 'backend')
from app.engineering.grid_geometry_pass import _find_confirmed_bubbles, _build_axis_tracks, _collect_dim_spans, to_frontend_dimension_lines

pdf = r'uploads\projects\b52ef5d6-04ac-4497-8793-de6902d5c06a\drawings\4f47d55c-2762-4242-9e40-29ad3e3f182e.pdf'
if not os.path.exists(pdf):
    pdf = r'backend\uploads\projects\b52ef5d6-04ac-4497-8793-de6902d5c06a\drawings\4f47d55c-2762-4242-9e40-29ad3e3f182e.pdf'
doc = fitz.open(pdf)
page = doc[14]
td = page.get_text("dict")
pw, ph = page.rect.width, page.rect.height

confirmed = _find_confirmed_bubbles(page, td)
print("Confirmed count:", len(confirmed))

# Check orientation for numbers
num_items = [c for c in confirmed if c["axis"] == "number"]
let_items = [c for c in confirmed if c["axis"] == "letter"]

print("\nNumbers with band_key=cx, pos_key=cy:")
tracks_num_y = _build_axis_tracks(confirmed, "number", pw, ph, band_key="cx", pos_key="cy")
for t in tracks_num_y:
    print("  Track:", t[1], [g["label"] for g in t[0]])

print("\nLetters with band_key=cy, pos_key=cx:")
tracks_let_x = _build_axis_tracks(confirmed, "letter", pw, ph, band_key="cy", pos_key="cx")
for t in tracks_let_x:
    print("  Track:", t[1], [g["label"] for g in t[0]])
