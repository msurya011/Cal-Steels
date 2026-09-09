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
print("plan_bounds:", plan_bounds)

out = M.detect_foundation_footings_grid(page, plan_bounds, scale_ratio=96)
print("N footings:", len(out))
for item in sorted(out, key=lambda i: (i["grid_ref"])):
    print(item["grid_ref"], "cx=",round(item["cx"],1), "cy=",round(item["cy"],1), "n_frags=",item["n_frags"], "span_w=",item["span_w"],"span_h=",item["span_h"])
