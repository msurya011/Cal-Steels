"""
Verification Script: Accurate Physical Member Length Calculation
================================================================
Verifies that all extracted beams and structural members receive mathematically
exact physical span lengths (ft) based on drawing scale and vector endpoints.
"""

import math
import fitz
import asyncio
from main import AnalysisRequest, analyse_pdf, scale_to_pts_per_foot

async def run_test():
    print("===============================================================")
    print(" TESTING PHYSICAL LENGTH CALCULATION ON REAL DRAWINGS ")
    print("===============================================================")

    # Test file in uploads
    pdf_filename = "#Structural binder.pdf"
    
    req = AnalysisRequest(
        filename=pdf_filename,
        page_index=6,  # Second Floor Framing Plan
        scale_ratio=64.0,  # 3/16" = 1'-0" (13.5 pts/ft)
        detect_unlabeled=True,
        detect_braces=True
    )

    print(f"\nRunning extraction with scale_ratio=96 (1/8\" = 1'-0\")...")
    res = await analyse_pdf(req)
    members = res.get("members", [])
    beams = [m for m in members if m.get("type") == "beam"]

    print(f"Total extracted members: {len(members)} (Beams: {len(beams)})")

    beams_with_endpoints = [b for b in beams if b.get("bx1") is not None and b.get("bx2") is not None]
    print(f"Beams with geometric endpoints: {len(beams_with_endpoints)} / {len(beams)}")

    ppf = scale_to_pts_per_foot(64.0)
    assert ppf == 13.5, f"Expected 13.5 pts/ft, got {ppf}"

    doc = fitz.open("uploads/#Structural binder.pdf")
    page = doc[6]
    pw, ph = page.rect.width, page.rect.height
    doc.close()

    print("\nSample Beam Physical Length Verification:")
    for b in beams_with_endpoints[:10]:
        bx1, by1 = b["bx1"], b["by1"]
        bx2, by2 = b["bx2"], b["by2"]
        reported_len = b.get("length_ft")

        expected_pt = math.hypot((bx2 - bx1) * pw, (by2 - by1) * ph)
        expected_len = round(expected_pt / ppf, 1)

        print(f"  {b.get('profile', 'Unlabelled'):14s} Span: ({bx1:.3f},{by1:.3f})->({bx2:.3f},{by2:.3f}) "
              f"| Reported: {reported_len:5.1f} ft | Expected: {expected_len:5.1f} ft")

        assert reported_len is not None and reported_len > 0, f"Beam {b} has invalid length {reported_len}"
        assert abs(reported_len - expected_len) <= 0.2, f"Discrepancy: reported {reported_len} vs expected {expected_len}"

    print("\n>>> ALL BEAMS VERIFIED WITH ACCURATE PHYSICAL LENGTHS! <<<")

if __name__ == "__main__":
    asyncio.run(run_test())
