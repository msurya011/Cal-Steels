import os
import sys
import json
import base64
from pathlib import Path
from dotenv import load_dotenv
import requests
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 1. Load API Key
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("[ERROR] GEMINI_API_KEY not found in .env")
    sys.exit(1)

# 2. Domain prompt.
#
# The prompt now lives in app/engineering/gemini_grid_prompt.py. It was moved
# out because it is the actual specification of this extractor -- the thing
# that decides what gets returned -- and it is now long enough that keeping it
# inline buried the code. It also asks for materially more than before: the
# grid LINE position as well as the bubble box, long multi-grid dimensions
# tagged separately so chain closure can be checked, and the scale note.
from app.engineering.gemini_grid_prompt import GEMINI_STRUCTURAL_PROMPT
from app.engineering.grid_reconcile import (
    reconcile_grids,
    check_chains,
    summarise,
)

def extract_grids_with_gemini(pdf_path: str, page_number: int = 0, output_image_path: str = "gemini_grid_takeoff.png"):
    print(f"\n[INFO] 1. Rendering PDF Page {page_number} to high-res image...")
    doc = fitz.open(pdf_path)
    page = doc[page_number]
    
    # Render at 100 DPI (~2400x1600 px) for crisp text with fast LLM throughput
    zoom = 100.0 / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    
    temp_img_path = "temp_gemini_input.png"
    pix.save(temp_img_path)
    
    # Ensure image max dimension <= 2048px for optimal LLM vision processing
    im = Image.open(temp_img_path)
    if max(im.size) > 2048:
        im.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        im.save(temp_img_path)
    
    img_w, img_h = im.size
    print(f"[INFO] Page prepared ({img_w}x{img_h} px).")
    
    # Read base64
    with open(temp_img_path, "rb") as f:
        img_bytes = f.read()
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    
    # Models to try in order of priority
    candidate_models = ["gemini-2.5-flash", "gemini-3.7-flash", "gemini-flash-latest", "gemini-2.5-pro"]
    
    res_data = None
    used_model = None
    
    for model_name in candidate_models:
        print(f"[INFO] 2. Calling Gemini ({model_name}) with Structural Engineering instructions...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        
        payload = {
            "contents": [{
                "parts": [
                    {"text": GEMINI_STRUCTURAL_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": img_b64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1
            }
        }
        
        headers = {"Content-Type": "application/json"}
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=60)
            if res.status_code == 200:
                res_data = res.json()
                used_model = model_name
                print(f"[SUCCESS] Model {model_name} responded successfully!")
                break
            else:
                print(f"[WARN] Model {model_name} returned {res.status_code}: {res.text[:200]}")
        except Exception as e:
            print(f"[WARN] Connection to {model_name} failed: {e}")

    if not res_data:
        print("[ERROR] All candidate Gemini models failed.")
        doc.close()
        return None

    raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
    
    try:
        structured_data = json.loads(raw_text)
    except Exception as e:
        print(f"[ERROR] Failed to parse JSON response: {e}")
        print("Raw Response:", raw_text[:500])
        doc.close()
        return None
        
    print("\n" + "="*60)
    print(f"[SUCCESS] Gemini Successfully Extracted Structural Grids & Dimensions!")
    print("="*60)
    
    v_grids = structured_data.get("vertical_grids", [])
    h_grids = structured_data.get("horizontal_grids", [])
    bays = structured_data.get("bay_dimensions", [])
    
    print(f"• Vertical Grids Detected ({len(v_grids)}): {[g.get('label') for g in v_grids]}")
    print(f"• Horizontal Grids Detected ({len(h_grids)}): {[g.get('label') for g in h_grids]}")
    print(f"• Bay Dimensions Extracted ({len(bays)}):")
    for b in bays[:8]:
        print(f"   - Bay {b.get('from_grid')} -> {b.get('to_grid')}: {b.get('dimension_text')} ({b.get('track', 'bay')})")
    if len(bays) > 8:
        print(f"   ... and {len(bays) - 8} more bays.")
        
    # 4. Verification overlay, drawn in the house annotation convention so a
    #    result can be compared directly against the marked-up reference
    #    sheets: RED box on every grid bubble, GREEN arrow for every span
    #    between two adjacent grids, YELLOW box on the scale note.
    print(f"\n[INFO] 3. Generating verification overlay: {output_image_path}...")
    base_img = Image.open(temp_img_path).convert("RGB")
    draw = ImageDraw.Draw(base_img)

    RED, GREEN, YELLOW = "#e00000", "#0d7a48", "#ffd400"

    def to_px(box):
        ymin, xmin, ymax, xmax = box
        return ((xmin / 1000.0) * img_w, (ymin / 1000.0) * img_h,
                (xmax / 1000.0) * img_w, (ymax / 1000.0) * img_h)

    def arrow(x0, y0, x1, y1):
        """Green span arrow: shaft plus a solid head at the far end."""
        draw.line([x0, y0, x1, y1], fill=GREEN, width=6)
        if abs(x1 - x0) >= abs(y1 - y0):
            d = 11 if x1 >= x0 else -11
            draw.polygon([(x1, y1), (x1 - d, y1 - 7), (x1 - d, y1 + 7)], fill=GREEN)
        else:
            d = 11 if y1 >= y0 else -11
            draw.polygon([(x1, y1), (x1 - 7, y1 - d), (x1 + 7, y1 - d)], fill=GREEN)

    # --- RED: one box per grid bubble, on every rail the model reported ---
    grid_line_px = {}
    for g in v_grids + h_grids:
        label = g.get("label")
        for bub in (g.get("bubbles") or []):
            box = bub.get("box_2d")
            if box and len(box) == 4:
                x0, y0, x1, y1 = to_px(box)
                draw.rectangle([x0, y0, x1, y1], outline=RED, width=3)
                draw.text((x0, max(0, y0 - 13)), str(label), fill=RED)
        # Fall back to the legacy flat box_2d shape if `bubbles` is absent.
        box = g.get("box_2d")
        if box and len(box) == 4 and not g.get("bubbles"):
            x0, y0, x1, y1 = to_px(box)
            draw.rectangle([x0, y0, x1, y1], outline=RED, width=3)
            draw.text((x0, max(0, y0 - 13)), str(label), fill=RED)

        pos = g.get("line_position")
        if pos is not None:
            axis = g.get("axis_type")
            grid_line_px[str(label)] = (
                (pos / 1000.0) * (img_w if axis == "vertical" else img_h), axis)

    # --- GREEN: one arrow per span, drawn BETWEEN THE GRID LINES ---
    #     The arrow deliberately runs line-to-line rather than bubble-to-bubble,
    #     because that is what the number underneath it actually measures.
    lanes = {}
    for b in bays:
        f, t = str(b.get("from_grid")), str(b.get("to_grid"))
        if f not in grid_line_px or t not in grid_line_px:
            continue
        p1, axis = grid_line_px[f]
        p2, _ = grid_line_px[t]
        # Stagger consecutive arrows so short adjacent spans stay legible --
        # the same reason the reference sheets stagger them.
        key = (axis, b.get("side"))
        lane = lanes.get(key, 0)
        lanes[key] = (lane + 1) % 3
        if axis == "vertical":
            y = img_h * (0.055 + lane * 0.030) if b.get("side") == "top" \
                else img_h * (0.945 - lane * 0.030)
            arrow(p1, y, p2, y)
            draw.text(((p1 + p2) / 2 - 22, y - 16), str(b.get("dimension_text") or ""), fill=GREEN)
        else:
            x = img_w * (0.055 + lane * 0.030) if b.get("side") == "left" \
                else img_w * (0.945 - lane * 0.030)
            arrow(x, p1, x, p2)
            draw.text((x + 8, (p1 + p2) / 2), str(b.get("dimension_text") or ""), fill=GREEN)

    # --- YELLOW: the scale note ---
    scale_box = (structured_data.get("scale") or {}).get("box_2d")
    if scale_box and len(scale_box) == 4:
        x0, y0, x1, y1 = to_px(scale_box)
        draw.rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], outline=YELLOW, width=4)

    base_img.save(output_image_path)
    print(f"[OK] Overlay saved to: {output_image_path}")

    # 5. Chain closure -- the one check that catches a MISSED grid, using only
    #    numbers the sheet itself carries.
    chains = check_chains(bays)
    if chains:
        print("\n[INFO] 4. Chain closure (multi-grid runs vs sum of their bays):")
        for c in chains:
            mark = {True: "PASS", False: "FAIL", None: "SKIP"}[c.get("pass")]
            print(f'   [{mark}] {c["span"]:<14} stated {c["stated_text"]}'
                  f'  sum {c["sum_of_parts_ft"]}'
                  + (f'  delta {c["delta_inches"]}"' if c.get("delta_inches") is not None else "")
                  + (f'  -- {c["diagnosis"]}' if c.get("diagnosis") else ""))
    else:
        print("\n[INFO] 4. No multi-grid dimension on this sheet -- chain closure "
              "cannot be checked. Grid recall is unverified.")
    structured_data["chain_checks"] = chains

    # 6. Reconcile against the deterministic vector pass.
    #
    #    GEOMETRY DECIDES WHERE, VISION DECIDES WHAT EXISTS. A grid both
    #    passes found is snapped to the exact vector coordinate; a grid only
    #    Gemini saw is kept but marked vision_only (its position is a
    #    normalised estimate off a <=2048px render -- about 2 inches per pixel
    #    on a D sheet at 1/8" scale, so it is never the thing to measure
    #    with); a grid only the vector pass found is surfaced too, because
    #    that means the vision pass missed it and the prompt asks for recall.
    try:
        from app.engineering.grid_geometry_pass import run_deterministic_geometry_pass
        geom = run_deterministic_geometry_pass(pdf_path, page_number)
    except Exception as e:
        geom = None
        print(f"\n[WARN] 5. Deterministic geometry pass unavailable "
              f"({type(e).__name__}: {e}) -- reporting Gemini output unreconciled.")

    if geom and geom.get("status") == "SUCCESS":
        pw = geom["page_dimensions"]["width"]
        ph = geom["page_dimensions"]["height"]
        rec_v = reconcile_grids(geom.get("vertical_grids", []), v_grids, pw, "x")
        rec_h = reconcile_grids(geom.get("horizontal_grids", []), h_grids, ph, "y")
        verdict = summarise(rec_v, rec_h, chains)
        structured_data["reconciled_grids"] = {"vertical": rec_v, "horizontal": rec_h}
        structured_data["reconciliation"] = verdict
        structured_data["scale_from_geometry"] = geom["scale"]

        print("\n[INFO] 5. Reconciliation with vector geometry:")
        print(f'   grids total          : {verdict["grids_total"]}')
        print(f'   confirmed by both    : {verdict["confirmed_by_both"]}')
        print(f'   geometry only (Gemini missed) : {verdict["geometry_only"]}')
        print(f'   vision only (no vector proof) : {verdict["vision_only"]}')
        print(f'   position disagreements        : {verdict["position_disagreements"]}')
        print(f'   VERDICT: {verdict["verdict"]}')
        if not geom["scale"]["is_explicit"]:
            print('   [note] no scale printed on the sheet -- geometry used a default; '
                  'the Gemini scale reading is the better source here')

    doc.close()
    return structured_data

if __name__ == "__main__":
    import sys
    import os
    from pathlib import Path

    def _pick_pdf_file() -> str:
        """Select a PDF file using CLI arguments or an interactive GUI file dialog."""
        if len(sys.argv) > 1 and sys.argv[1].strip():
            arg_path = sys.argv[1].strip()
            if os.path.exists(arg_path):
                return arg_path
            print(f"Warning: Specified file not found: {arg_path}")

        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askopenfilename(
                title="Select Structural/Architectural PDF Drawing",
                filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")]
            )
            root.destroy()
            if selected and os.path.exists(selected):
                return selected
        except Exception:
            pass

        default_pdf = r"d:\Steel-ghost 2\Steel-ghost\AI_Extraction\pdf's\Structural snaps.pdf"
        if os.path.exists(default_pdf):
            return default_pdf

        return ""

    test_pdf = _pick_pdf_file()
    page_num = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    if not test_pdf or not os.path.exists(test_pdf):
        print("No valid PDF file selected or provided.")
        print("Usage: python extract_grids_gemini.py [path_to_pdf] [page_number]")
        sys.exit(1)

    print(f"--- Running Gemini Grid Extraction on: {Path(test_pdf).name} (page {page_num+1}) ---")
    extract_grids_with_gemini(test_pdf, page_number=page_num, output_image_path="gemini_structural_takeoff.png")

