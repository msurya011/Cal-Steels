import os
from pathlib import Path
from app.engineering.grid_geometry_pass import run_deterministic_geometry_pass

pdf_dir = Path(r"d:\Steel-ghost 2\Steel-ghost\AI_Extraction\pdf's")
print(f"Directory exists: {pdf_dir.exists()}")

for pdf_path in pdf_dir.glob("*.pdf"):
    print(f"\n==================================================")
    print(f"PDF: {pdf_path.name}")
    res = run_deterministic_geometry_pass(pdf_path, page_number=0)
    print(f"  Scale: {res['scale']['scale_string']} ({res['scale']['points_per_foot']} pts/ft)")
    print(f"  Vertical Grids ({len(res['vertical_grids'])}): {[g['label'] for g in res['vertical_grids'][:8]]}...")
    print(f"  Horizontal Grids ({len(res['horizontal_grids'])}): {[g['label'] for g in res['horizontal_grids'][:8]]}...")
    print(f"  Total Intersections: {res['total_intersections_count']}")
    print(f"  Horizontal Bay Chains: {res['total_horizontal_bays_count']}")
    print(f"  Vertical Bay Chains: {res['total_vertical_bays_count']}")
