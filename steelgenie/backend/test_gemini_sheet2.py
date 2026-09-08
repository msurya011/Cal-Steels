import os
import shutil
from pathlib import Path
from extract_grids_gemini import extract_grids_with_gemini

pdf_dir = Path("d:/Steel-ghost 2/Steel-ghost/AI_Extraction/pdf's")
target_pdf = pdf_dir / "Broadway binder-6-10.pdf"

print(f"Target PDF exists: {target_pdf.exists()} -> {target_pdf}")

out_img = "gemini_broadway_takeoff.png"
res = extract_grids_with_gemini(str(target_pdf), page_number=0, output_image_path=out_img)

if res:
    dst = Path(r"C:\Users\user\.gemini\antigravity-ide\brain\303092a6-26fe-43df-acd5-0a425b07eeab") / out_img
    shutil.copyfile(out_img, dst)
    print(f"\n[DONE] Copied visual verification to: {dst}")
