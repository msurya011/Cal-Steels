"""
Official AISC Shapes Database v16.0 Master Ingestor
===================================================
Ingests all 2,302 structural steel shapes from:
d:/Steel-ghost 2/Steel-ghost/steelgenie/backend/data/aisc-shapes-database-v160-2.xlsx
"""

import os
import re
import json
import csv
import openpyxl

def ingest_official_aisc_v16():
    excel_path = os.path.join(os.path.dirname(__file__), "data", "aisc-shapes-database-v160-2.xlsx")
    if not os.path.exists(excel_path):
        print(f"Error: {excel_path} not found!")
        return

    print("=================================================================")
    print(" INGESTING OFFICIAL AISC SHAPES DATABASE v16.0 ")
    print("=================================================================")
    print(f"Loading Excel file: {os.path.basename(excel_path)}...")

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    if "Database v16.0" not in wb.sheetnames:
        print(f"Error: 'Database v16.0' sheet not found in workbook. Available: {wb.sheetnames}")
        return

    sheet = wb["Database v16.0"]
    headers = [str(cell.value or "").strip() for cell in sheet[1]]
    
    # Locate column indices (first occurrence is US Imperial, later columns are Metric SI)
    col_idx = {}
    for i, name in enumerate(headers):
        if name not in col_idx:
            col_idx[name] = i

    type_col = col_idx.get("Type", 0)
    edi_col = col_idx.get("EDI_Std_Nomenclature", 1)
    label_col = col_idx.get("AISC_Manual_Label", 2)
    weight_col = col_idx.get("W", 4)
    area_col = col_idx.get("A", 5)
    depth_col = col_idx.get("d", 6)
    flange_w_col = col_idx.get("bf", 11)
    web_t_col = col_idx.get("tw", 16)
    flange_t_col = col_idx.get("tf", 19)

    master_db = {}
    csv_rows = []

    def clean_num(val):
        if val is None or val == "" or val == "-" or str(val).strip() == "":
            return None
        try:
            return float(val)
        except Exception:
            return None

    for row in sheet.iter_rows(min_row=2, values_only=True):
        stype = str(row[type_col] or "").strip().upper()
        edi_name = str(row[edi_col] or "").strip().upper()
        manual_label = str(row[label_col] or "").strip().upper()

        if not edi_name and not manual_label:
            continue

        primary_name = manual_label if manual_label else edi_name
        weight = clean_num(row[weight_col])
        if weight is None or weight <= 0:
            continue

        area = clean_num(row[area_col])
        depth = clean_num(row[depth_col])
        flange_w = clean_num(row[flange_w_col])
        web_t = clean_num(row[web_t_col])
        flange_t = clean_num(row[flange_t_col])

        shape_entry = {
            "type": stype,
            "edi_name": edi_name,
            "manual_label": manual_label,
            "weight_lb_ft": round(weight, 2),
            "area_sq_in": round(area, 2) if area else None,
            "depth_in": round(depth, 3) if depth else None,
            "flange_w_in": round(flange_w, 3) if flange_w else None,
            "web_t_in": round(web_t, 3) if web_t else None,
            "flange_t_in": round(flange_t, 3) if flange_t else None,
        }

        # Index under primary designation
        norm_key = primary_name.replace(" ", "").replace("×", "X").upper()
        master_db[norm_key] = shape_entry

        # Also alias EDI standard nomenclature if different
        if edi_name and edi_name != primary_name:
            edi_key = edi_name.replace(" ", "").replace("×", "X").upper()
            if edi_key not in master_db:
                master_db[edi_key] = shape_entry

        # Alias without hyphens e.g. PIPE3-1/2STD -> PIPE3.5STD / PIPE3-1/2STD
        if "-" in norm_key:
            master_db[norm_key.replace("-", "")] = shape_entry

        csv_rows.append([
            norm_key, stype, edi_name, manual_label,
            shape_entry["weight_lb_ft"], shape_entry["area_sq_in"],
            shape_entry["depth_in"], shape_entry["flange_w_in"],
            shape_entry["web_t_in"], shape_entry["flange_t_in"]
        ])

    data_dir = os.path.join(os.path.dirname(__file__), "data")
    json_path = os.path.join(data_dir, "aisc_v16_shapes.json")
    csv_path = os.path.join(data_dir, "aisc_v16_shapes.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(master_db, f, indent=2)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["designation", "type", "edi_name", "manual_label", "weight_lb_ft", "area_sq_in", "depth_in", "flange_w_in", "web_t_in", "flange_t_in"])
        writer.writerows(csv_rows)

    print(f"\n[SUCCESS] Loaded {len(master_db)} AISC v16.0 shapes from official Excel database!")
    print(f"  • JSON Master Catalog: {json_path}")
    print(f"  • CSV Catalog:         {csv_path}")

    # Shape type breakdown
    type_counts = {}
    for entry in master_db.values():
        t = entry["type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"\nBreakdown by Shape Type: {type_counts}")

if __name__ == "__main__":
    ingest_official_aisc_v16()
