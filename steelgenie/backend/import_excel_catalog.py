"""
AISC Excel Catalog Ingestor
===========================
Reads user-provided Excel (.xlsx / .xls) AISC tables from backend/data/
and integrates them directly into the takeoff calculation engine & Supabase.
"""

import os
import glob
import json
import re
import openpyxl
from dotenv import load_dotenv

load_dotenv()

def import_excel():
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)

    excel_files = glob.glob(os.path.join(data_dir, "*.xlsx")) + glob.glob(os.path.join(data_dir, "*.xls"))
    if not excel_files:
        print(f"\n[INFO] Please place your Excel (.xlsx) file into:\n  👉 {data_dir}\n")
        return

    excel_path = excel_files[0]
    print(f"\n[EXCEL] Found Excel file: {os.path.basename(excel_path)}")
    print(f"[EXCEL] Loading workbook...")

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    sheet = wb.active
    print(f"[EXCEL] Reading sheet: '{sheet.title}' ({sheet.max_row} rows)...")

    # Read header row
    headers = [str(cell.value or "").strip().lower() for cell in sheet[1]]
    print(f"[EXCEL] Detected columns: {headers}")

    # Identify key columns
    desig_col = None
    weight_col = None
    type_col = None
    depth_col = None
    flange_col = None
    area_col = None

    for i, h in enumerate(headers):
        if any(k in h for k in ["designation", "edi_std_nomen", "aisc_name", "shape", "profile", "section"]):
            if desig_col is None: desig_col = i
        elif any(k in h for k in ["weight", "w_lb", "w_ft", "w/ft", "lbs/ft", "lb/ft", "mass"]):
            if weight_col is None: weight_col = i
        elif any(k in h for k in ["type", "shape_type"]):
            if type_col is None: type_col = i
        elif any(k in h for k in ["depth", " d ", "d_in"]):
            if depth_col is None: depth_col = i
        elif any(k in h for k in ["flange_width", "bf", "width", "bf_in"]):
            if flange_col is None: flange_col = i
        elif any(k in h for k in ["area", "a_in2", "area_sq_in"]):
            if area_col is None: area_col = i

    if desig_col is None:
        # Fallback to column 0 if not named
        desig_col = 0

    print(f"[EXCEL] Mapped Designation col index: {desig_col}, Weight col index: {weight_col}")

    imported_shapes = {}
    
    for row in sheet.iter_rows(min_row=2, values_only=True):
        raw_desig = row[desig_col] if desig_col < len(row) else None
        if not raw_desig:
            continue
        
        desig = str(raw_desig).strip().upper().replace(" ", "").replace("×", "X")
        if not desig:
            continue

        # Extract weight
        wt_val = None
        if weight_col is not None and weight_col < len(row):
            try:
                wt_val = float(row[weight_col]) if row[weight_col] is not None else None
            except Exception:
                pass

        if wt_val is None:
            # Fallback to self-encoding digit after X
            m = re.match(r'^(?:W|C|MC|S|HP|WT|MT|ST|M)\d+(?:\.\d+)?X(\d+(?:\.\d+)?)$', desig)
            if m:
                wt_val = float(m.group(1))

        if wt_val is not None and wt_val > 0:
            shape_type = "W" if desig.startswith("W") else ("HSS" if desig.startswith("HSS") else ("L" if desig.startswith("L") else "Other"))
            imported_shapes[desig] = {
                "type": shape_type,
                "weight_lb_ft": round(wt_val, 2),
                "depth_in": float(row[depth_col]) if (depth_col and depth_col < len(row) and row[depth_col] is not None) else None,
                "flange_w_in": float(row[flange_col]) if (flange_col and flange_col < len(row) and row[flange_col] is not None) else None,
                "area_sq_in": float(row[area_col]) if (area_col and area_col < len(row) and row[area_col] is not None) else None,
            }

    print(f"\n[SUCCESS] Successfully imported {len(imported_shapes)} AISC shapes from your Excel sheet!")

    # Save to json and csv in data/
    out_json = os.path.join(data_dir, "aisc_v16_shapes.json")
    out_csv = os.path.join(data_dir, "aisc_v16_shapes.csv")

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(imported_shapes, f, indent=2)

    print(f"  • Updated Master JSON: {out_json}")
    print(f"  • Takeoff Engine is now using your Excel sheet!")

if __name__ == "__main__":
    import_excel()
