import os
import sys
import json
import base64
import re
from pathlib import Path
from fractions import Fraction
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

# Senior Structural Estimator System Prompt
ESTIMATOR_PROMPT = """
You are a Senior Structural Steel Estimator (PE / QTO Takeoff Director) with 25+ years of experience in structural steel fabrication and erection takeoff.

In professional steel takeoff (like in Bluebeam Revu / PlanSwift / Tekla), an estimator follows these strict core rules:

---
### GRID COMPLETENESS — CRITICAL (HIGH RECALL & DOUBLE-SCAN):
The primary objective is GRID RECALL. You must identify ALL grid lines/bubbles visible in the drawing. Missing a real grid is an error.

Before producing the final answer, perform a second complete scan of the drawing specifically for missed grids.
Scan systematically:
1. Top margin
2. Bottom margin
3. Left margin
4. Right margin
5. Interior drawing area
6. Any grid labels/bubbles that may be partially separated from the main drawing

A grid must be included if there is sufficient visual evidence that it is a structural reference grid.
Do NOT stop after finding the obvious grids. After detecting the first set of grids, scan again for:
- additional numbered grids
- additional lettered grids
- decimal/sub-grids (e.g. 1.9, 2.5, 6.5, 6.8, B.2, C.6)
- grids appearing only on one margin (e.g. bottom-only or right-only bubbles)
- grids with labels/bubbles that are far from the main grid area
- grids whose line is faint, partially interrupted, or obscured
- grids that do not intersect columns or beams

IMPORTANT:
- Grid detection does NOT require a grid to intersect a structural column or beam. A grid may exist even when there is no column/grid intersection visible.
- If a grid is clearly present, include it even if its line is partially interrupted or its bubble appears only on one margin.
- NEVER create or mark a grid when there is no visual evidence of that grid.
- Do not return dimensions, beams, columns, section bubbles, detail bubbles, or dimension lines as grids.

---
### SENIOR ESTIMATOR TAKEOFF STANDARDS:
1. **Primary Grids vs Sub-Grids (Continuous Building Skeleton)**:
   - **Primary Grids (Master Grids 1, 2, 3... and A, B, C...)**: These define the master building columns and ALWAYS run continuously all the way from START to END (Top to Bottom, and Left to Right) across the entire building.
   - Even if circular bubbles only appear on the top margin, those primary grid lines extend ALL THE WAY to the bottom margin to anchor the bottom dimension string!
   - **Sub-Grids (Decimal Grids 1.9, 2.5, 6.5, 6.8 and B.2, C.6)**: These are local intermediate framing lines (e.g. for stairs, canopies, or special bays) that only span their local zone and terminate when their framing finishes.

2. **Perimeter Scanning on ALL 4 Margins (Top, Bottom, Left, Right)**:
   - **Top Margin**: Scan for top dimension strings connecting grid bubbles.
   - **Bottom Margin (MANDATORY)**: Scan the bottom margin below the building framing! The primary grids from the top continue all the way down to the bottom and connect to bottom dimension strings (plus any local bottom sub-grid bubbles like 6.5, 6.8). You MUST extract the bottom dimension chain!
   - **Right Margin**: Scan for right vertical dimension strings connecting letter grids.
   - **Left Margin**: Scan for left vertical dimension strings (if present on the drawing).

3. **Connecting Grid to Dimension (Witness / Extension Lines)**:
   - For every dimension string (e.g. `33'-0"`, `32'-8"`), identify the EXACT `from_grid` and `to_grid` it physically bridges between.
   - Read exact fractional feet & inches (`29'-8"`, `3'-0"`, `33'-0"`, `32'-8"`, `36'-8"`, `32'-4"`, `11'-4"`, `4'-0"`).

---
### OUTPUT JSON SCHEMA (Strict JSON):
{
  "drawing_title": "string",
  "detected_scale": "string", // e.g. "1/8\" = 1'-0\""
  "grid_axes": [
    {
      "label": "1",
      "axis_orientation": "vertical", // "vertical" for number grids (X-axis), "horizontal" for letter grids (Y-axis)
      "bubble_box": [ymin, xmin, ymax, xmax], // normalized 0-1000
      "margin_side": "top" // "top", "bottom", "left", "right"
    }
  ],
  "top_dimension_bays": [
    {
      "from_grid": "1",
      "to_grid": "2",
      "dimension_text": "31'-4\"",
      "track_level": 1,
      "box_2d": [ymin, xmin, ymax, xmax] // normalized 0-1000
    }
  ],
  "bottom_dimension_bays": [
    {
      "from_grid": "1",
      "to_grid": "2",
      "dimension_text": "32'-8\"",
      "track_level": 1,
      "box_2d": [ymin, xmin, ymax, xmax] // normalized 0-1000
    }
  ],
  "right_dimension_bays": [
    {
      "from_grid": "A",
      "to_grid": "B",
      "dimension_text": "24'-0\"",
      "track_level": 1,
      "box_2d": [ymin, xmin, ymax, xmax] // normalized 0-1000
    }
  ],
  "left_dimension_bays": [
    {
      "from_grid": "A",
      "to_grid": "B",
      "dimension_text": "24'-0\"",
      "track_level": 1,
      "box_2d": [ymin, xmin, ymax, xmax] // normalized 0-1000
    }
  ]
}
"""

def parse_ft_in_to_inches(text: str) -> float:
    """Accurately convert dimension string '24'-6 1/2\"' to decimal inches."""
    if not text:
        return 0.0
    t = text.strip().replace(" ", "").replace("’", "'").replace("”", '"')
    
    # Check feet and inches pattern
    m = re.match(r"""^(?:\(?\s*)?(?P<feet>\d+)\s*[']\s*[-–—]?\s*(?:(?P<inches>\d+)(?:\s+(?P<num>\d+)\s*/\s*(?P<den>\d+))?\s*["])?(?:\s*\)?\s*)?$""", t)
    if m:
        feet = float(m.group("feet"))
        inches = float(m.group("inches") or 0)
        num = float(m.group("num") or 0)
        den = float(m.group("den") or 1)
        fraction = (num / den) if den != 0 else 0
        return (feet * 12.0) + inches + fraction
    
    # Check inch-only pattern e.g. 1'-7/8" or 8 1/2"
    m_inch = re.match(r"""^(?:\(?\s*)?(?:(?P<feet>\d+)[']\s*[-–—]?)?(?P<num>\d+)/(?P<den>\d+)\s*["](?:\s*\)?\s*)?$""", t)
    if m_inch:
        feet = float(m_inch.group("feet") or 0)
        num = float(m_inch.group("num"))
        den = float(m_inch.group("den"))
        return (feet * 12.0) + (num / den)
    
    # Simple fallback numbers
    m_num = re.findall(r"\d+", t)
    if m_num:
        return float(m_num[0]) * 12.0
    return 0.0

def run_estimator_takeoff(pdf_path: str, page_number: int = 0, output_image: str = "estimator_takeoff_verified.png"):
    print("="*75)
    print(f"📐 RUNNING LEAD STRUCTURAL ESTIMATOR TAKEOFF ON: {Path(pdf_path).name} (Page {page_number})")
    print("="*75)
    
    doc = fitz.open(pdf_path)
    page = doc[page_number]
    
    # Render crisp image
    zoom = 100.0 / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    temp_img = "temp_estimator_page.png"
    pix.save(temp_img)
    
    im = Image.open(temp_img)
    if max(im.size) > 2048:
        im.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        im.save(temp_img)
    img_w, img_h = im.size
    
    with open(temp_img, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
        
    # Multi-model fallback list
    candidate_models = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.7-flash", "gemini-flash-latest"]
    res_data = None
    
    for model_name in candidate_models:
        print(f"🤖 Invoking Gemini AI Estimator Engine ({model_name})...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        
        payload = {
            "contents": [{
                "parts": [
                    {"text": ESTIMATOR_PROMPT},
                    {"inline_data": {"mime_type": "image/png", "data": img_b64}}
                ]
            }],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.0
            }
        }
        
        try:
            res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=90)
            if res.status_code == 200:
                res_data = res.json()
                print(f"[SUCCESS] Model {model_name} responded successfully!")
                break
            else:
                print(f"[WARN] Model {model_name} returned {res.status_code}: {res.text[:150]}")
        except Exception as e:
            print(f"[WARN] Connection to {model_name} failed: {e}")


    if not res_data:
        print("[ERROR] All candidate Gemini models failed.")
        doc.close()
        return None

        
    raw_json = res_data["candidates"][0]["content"]["parts"][0]["text"]
    data = json.loads(raw_json)
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        data = data[0]
    elif not isinstance(data, dict):
        data = {}

    # Extract all 4 perimeter tracks
    grid_axes = data.get("grid_axes", [])
    top_bays = data.get("top_dimension_bays", [])
    bot_bays = data.get("bottom_dimension_bays", [])
    right_bays = data.get("right_dimension_bays", [])
    left_bays = data.get("left_dimension_bays", [])
    
    # Fallback to consecutive_bay_dimensions if old format
    if not (top_bays or bot_bays or right_bays or left_bays):
        old_bays = data.get("consecutive_bay_dimensions", [])
        top_bays = [b for b in old_bays if b.get("axis_orientation") == "horizontal"]
        right_bays = [b for b in old_bays if b.get("axis_orientation") == "vertical"]

    def _process_track(bays, title):
        if not bays:
            return 0.0
        print("\n" + "—"*80)
        print(f"📊 {title}:")
        print("—"*80)
        print(f"{'BAY SPAN':<18} | {'DIMENSION TEXT':<16} | {'LENGTH (IN)':<12} | {'LENGTH (FT)':<12} | {'CUMULATIVE STATION'}")
        print("—"*80)
        cum = 0.0
        for bay in bays:
            dim_text = bay.get("dimension_text", "")
            total_in = parse_ft_in_to_inches(dim_text)
            dec_ft = total_in / 12.0
            cum += dec_ft
            bay["total_inches"] = round(total_in, 3)
            bay["decimal_feet"] = round(dec_ft, 3)
            bay["cumulative_station_ft"] = round(cum, 3)
            span_str = f"Grid {bay.get('from_grid')} -> {bay.get('to_grid')}"
            print(f"{span_str:<18} | {dim_text:<16} | {total_in:<12.2f} | {dec_ft:<12.2f} | {cum:.2f} ft ({int(cum)}'-{round((cum%1)*12, 1)}\")")
        print("—"*80)
        print(f"📐 TOTAL CALCULATED SPAN: {cum:.2f} ft ({cum*12.0:.1f} inches)")
        return cum

    _process_track(top_bays, "TOP HORIZONTAL DIMENSION TRACK (X-AXIS)")
    _process_track(bot_bays, "BOTTOM HORIZONTAL DIMENSION TRACK (X-AXIS)")
    _process_track(right_bays, "RIGHT VERTICAL DIMENSION TRACK (Y-AXIS)")
    _process_track(left_bays, "LEFT VERTICAL DIMENSION TRACK (Y-AXIS)")

    # Render Senior Estimator Verification Overlay
    base_img = Image.open(temp_img).convert("RGB")
    draw = ImageDraw.Draw(base_img)
    
    # 1. Map Grid Bubbles and draw continuous Top-to-Bottom Primary Grid Lines
    grid_map = {}
    for g in grid_axes:
        box = g.get("bubble_box")
        lbl = str(g.get("label", ""))
        if box and len(box) == 4:
            ymin, xmin, ymax, xmax = box
            y0, x0, y1, x1 = (ymin/1000.0)*img_h, (xmin/1000.0)*img_w, (ymax/1000.0)*img_h, (xmax/1000.0)*img_w
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            grid_map[lbl] = (cx, cy)
            
            # Draw bubble outline
            color = "#d946ef" if g.get("axis_orientation") == "vertical" or g.get("margin_side") in ("top", "bottom") else "#06b6d4"
            draw.ellipse([x0, y0, x1, y1], outline=color, width=3)
            draw.text((x0 + 4, y0 + 2), lbl, fill=color)
            
            # If this is a primary vertical grid (e.g. 1, 2, 3... at top), draw centerline extending down to bottom!
            if g.get("axis_orientation") == "vertical" or g.get("margin_side") == "top":
                draw.line([(cx, cy), (cx, img_h * 0.95)], fill="#94a3b8", width=1)
            elif g.get("axis_orientation") == "horizontal" or g.get("margin_side") in ("right", "left"):
                draw.line([(img_w * 0.05, cy), (cx, cy)], fill="#94a3b8", width=1)

    # 2. Draw Dimension Banners & Witness Lines across all tracks
    tracks_to_draw = [
        (top_bays, "#22c55e"),      # Green for top
        (bot_bays, "#ec4899"),      # Pink for bottom
        (right_bays, "#06b6d4"),    # Cyan for right
        (left_bays, "#f59e0b"),     # Amber for left
    ]
    
    for track_bays, color in tracks_to_draw:
        for bay in track_bays:
            box = bay.get("box_2d")
            f_lbl = str(bay.get("from_grid", ""))
            t_lbl = str(bay.get("to_grid", ""))
            dim_str = bay.get("dimension_text", "")
            
            if box and len(box) == 4:
                ymin, xmin, ymax, xmax = box
                y0, x0, y1, x1 = (ymin/1000.0)*img_h, (xmin/1000.0)*img_w, (ymax/1000.0)*img_h, (xmax/1000.0)*img_w
                dim_cx, dim_cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                
                # Draw dimension box and label banner
                draw.rectangle([x0, y0, x1, y1], outline=color, width=2)
                banner = f"{f_lbl}->{t_lbl}: {dim_str}"
                draw.text((x0, max(0, y0 - 14)), banner, fill=color)
                
                # Witness lines connecting from grid line X/Y to the dimension box
                if f_lbl in grid_map:
                    fcx, fcy = grid_map[f_lbl]
                    draw.line([(fcx, dim_cy), (x0, dim_cy)], fill="#eab308", width=1)
                if t_lbl in grid_map:
                    tcx, tcy = grid_map[t_lbl]
                    draw.line([(tcx, dim_cy), (x1, dim_cy)], fill="#eab308", width=1)
                    
    base_img.save(output_image)
    print(f"\n[OK] Senior Estimator Markup saved to: {output_image}")
    
    # Save to artifacts
    dst = Path(r"C:\Users\user\.gemini\antigravity-ide\brain\303092a6-26fe-43df-acd5-0a425b07eeab") / output_image
    base_img.save(dst)
    
    doc.close()
    return data


if __name__ == "__main__":
    target_pdf = r"d:\Steel-ghost 2\Steel-ghost\AI_Extraction\pdf's\Structural snaps.pdf"
    run_estimator_takeoff(target_pdf, page_number=0, output_image="estimator_takeoff_verified.png")
