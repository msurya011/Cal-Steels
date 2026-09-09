import builtins
from starlette.requests import Request
builtins.Request = Request
import sys, os
sys.path.insert(0, os.getcwd())
import fitz
import main as M

pdf_path = os.path.expanduser("~/mnt/Steel-ghost 2/Steel-ghost/AI_Extraction/pdf's/Thaddeus Stevens College-Multipurpose-Dorm Bldg-Structural-5-10.pdf")
doc = fitz.open(pdf_path)
page = doc[1]
page_w, page_h = page.rect.width, page.rect.height
text_dict = page.get_text("dict")
plan_bounds = M.find_plan_boundary(page, page_w, page_h, text_dict=text_dict)
print("page_w,page_h:", page_w, page_h)
print("plan_bounds:", plan_bounds)

v_grid, h_grid, v_labels, h_labels = M.extract_grid_lines(page, page_w, page_h, plan_bounds, text_dict=text_dict)
print("=== V GRID ===")
for x in sorted(v_grid):
    print(round(x,1), v_labels.get(x))
print("=== H GRID ===")
for y in sorted(h_grid):
    print(round(y,1), h_labels.get(y))
