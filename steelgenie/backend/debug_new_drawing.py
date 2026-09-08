import fitz
import sys
import os
sys.path.insert(0, 'backend')
from app.engineering.grid_geometry_pass import _find_confirmed_bubbles, _collect_dim_spans, run_deterministic_geometry_pass, to_frontend_dimension_lines

pdf = r'uploads\projects\b52ef5d6-04ac-4497-8793-de6902d5c06a\drawings\4f47d55c-2762-4242-9e40-29ad3e3f182e.pdf'
if not os.path.exists(pdf):
    pdf = r'backend\uploads\projects\b52ef5d6-04ac-4497-8793-de6902d5c06a\drawings\4f47d55c-2762-4242-9e40-29ad3e3f182e.pdf'

doc = fitz.open(pdf)
print("Page count:", len(doc))
for i in range(len(doc)):
    page = doc[i]
    t = page.get_text()
    if "17'-10\"" in t or "17'-10" in t or "25'-1\"" in t:
        print(f"\n=== MATCH PAGE {i} ===")
        td = page.get_text("dict")
        bubbles = _find_confirmed_bubbles(page, td)
        print("Confirmed bubbles:", len(bubbles))
        for b in bubbles:
            print("  bubble:", b)
        dims = _collect_dim_spans(td)
        print("Dim spans:", len(dims))
        for d in dims:
            print("  dim:", d)
        res = run_deterministic_geometry_pass(pdf, page_number=i, override_pts_per_foot=864.0/96.0)
        fd_dims = to_frontend_dimension_lines(res)
        print("Calculated frontend dims count:", len(fd_dims))
