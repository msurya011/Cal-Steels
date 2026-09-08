import os
import shutil
from pathlib import Path
from estimator_gemini_takeoff import run_estimator_takeoff

pdf_dir = Path("d:/Steel-ghost 2/Steel-ghost/AI_Extraction/pdf's")
target_pdf = pdf_dir / "Structural snaps.pdf"
out_img = "structural_snaps_estimator_markup.png"

print(f"Target PDF exists: {target_pdf.exists()} -> {target_pdf}")

data = run_estimator_takeoff(str(target_pdf), page_number=0, output_image=out_img)

if data:
    dst = Path(r"C:\Users\user\.gemini\antigravity-ide\brain\303092a6-26fe-43df-acd5-0a425b07eeab") / out_img
    shutil.copyfile(out_img, dst)
    print(f"\n[DONE] Successfully saved visual verification to: {dst}")
