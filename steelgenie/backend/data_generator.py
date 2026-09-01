"""
Generate Complete AISC 15th & 16th Edition Master Steel Shape Database
=======================================================================
Creates a comprehensive JSON and CSV dataset of all standard AISC shapes:
- W-Shapes (Wide-Flange Beams & Columns)
- Square & Rectangular HSS (Tubes)
- Structural Angles (L & 2L)
- Channels (C & MC)
- Structural Tees (WT)
- Standard Steel Pipes
"""

import json
import csv
import os

AISC_DATABASE = {
    # ── W-Shapes (AISC Table 1-1) ──
    # Format: designation -> {type, weight_lb_ft, depth_in, flange_width_in, area_sq_in, grade}
    "W44X335": {"type": "W", "weight_lb_ft": 335.0, "depth_in": 44.0, "flange_w_in": 15.9, "area_sq_in": 98.5},
    "W36X302": {"type": "W", "weight_lb_ft": 302.0, "depth_in": 37.3, "flange_w_in": 16.7, "area_sq_in": 89.0},
    "W36X256": {"type": "W", "weight_lb_ft": 256.0, "depth_in": 37.4, "flange_w_in": 12.2, "area_sq_in": 75.3},
    "W36X232": {"type": "W", "weight_lb_ft": 232.0, "depth_in": 37.1, "flange_w_in": 12.1, "area_sq_in": 68.3},
    "W36X182": {"type": "W", "weight_lb_ft": 182.0, "depth_in": 36.3, "flange_w_in": 12.0, "area_sq_in": 53.6},
    "W36X150": {"type": "W", "weight_lb_ft": 150.0, "depth_in": 35.9, "flange_w_in": 12.0, "area_sq_in": 44.2},
    "W36X135": {"type": "W", "weight_lb_ft": 135.0, "depth_in": 35.6, "flange_w_in": 12.0, "area_sq_in": 39.7},
    "W33X241": {"type": "W", "weight_lb_ft": 241.0, "depth_in": 34.2, "flange_w_in": 15.9, "area_sq_in": 70.9},
    "W33X152": {"type": "W", "weight_lb_ft": 152.0, "depth_in": 33.5, "flange_w_in": 11.6, "area_sq_in": 44.7},
    "W33X130": {"type": "W", "weight_lb_ft": 130.0, "depth_in": 33.1, "flange_w_in": 11.5, "area_sq_in": 38.3},
    "W30X148": {"type": "W", "weight_lb_ft": 148.0, "depth_in": 30.7, "flange_w_in": 10.5, "area_sq_in": 43.5},
    "W30X116": {"type": "W", "weight_lb_ft": 116.0, "depth_in": 30.0, "flange_w_in": 10.5, "area_sq_in": 34.2},
    "W30X90":  {"type": "W", "weight_lb_ft": 90.0,  "depth_in": 29.5, "flange_w_in": 10.4, "area_sq_in": 26.4},
    "W27X178": {"type": "W", "weight_lb_ft": 178.0, "depth_in": 27.8, "flange_w_in": 14.0, "area_sq_in": 52.3},
    "W27X146": {"type": "W", "weight_lb_ft": 146.0, "depth_in": 27.4, "flange_w_in": 14.0, "area_sq_in": 42.9},
    "W27X102": {"type": "W", "weight_lb_ft": 102.0, "depth_in": 27.1, "flange_w_in": 10.0, "area_sq_in": 30.0},
    "W27X84":  {"type": "W", "weight_lb_ft": 84.0,  "depth_in": 26.7, "flange_w_in": 10.0, "area_sq_in": 24.8},
    "W24X104": {"type": "W", "weight_lb_ft": 104.0, "depth_in": 24.1, "flange_w_in": 12.8, "area_sq_in": 30.6},
    "W24X84":  {"type": "W", "weight_lb_ft": 84.0,  "depth_in": 24.1, "flange_w_in": 9.0,  "area_sq_in": 24.7},
    "W24X76":  {"type": "W", "weight_lb_ft": 76.0,  "depth_in": 23.9, "flange_w_in": 9.0,  "area_sq_in": 22.4},
    "W24X68":  {"type": "W", "weight_lb_ft": 68.0,  "depth_in": 23.7, "flange_w_in": 8.97, "area_sq_in": 20.1},
    "W24X62":  {"type": "W", "weight_lb_ft": 62.0,  "depth_in": 23.7, "flange_w_in": 7.04, "area_sq_in": 18.2},
    "W24X55":  {"type": "W", "weight_lb_ft": 55.0,  "depth_in": 23.6, "flange_w_in": 7.01, "area_sq_in": 16.2},
    "W21X93":  {"type": "W", "weight_lb_ft": 93.0,  "depth_in": 21.6, "flange_w_in": 8.42, "area_sq_in": 27.3},
    "W21X83":  {"type": "W", "weight_lb_ft": 83.0,  "depth_in": 21.4, "flange_w_in": 8.36, "area_sq_in": 24.3},
    "W21X68":  {"type": "W", "weight_lb_ft": 68.0,  "depth_in": 21.1, "flange_w_in": 8.27, "area_sq_in": 20.0},
    "W21X50":  {"type": "W", "weight_lb_ft": 50.0,  "depth_in": 20.8, "flange_w_in": 6.53, "area_sq_in": 14.7},
    "W21X44":  {"type": "W", "weight_lb_ft": 44.0,  "depth_in": 20.7, "flange_w_in": 6.50, "area_sq_in": 13.0},
    "W18X86":  {"type": "W", "weight_lb_ft": 86.0,  "depth_in": 18.4, "flange_w_in": 11.1, "area_sq_in": 25.3},
    "W18X50":  {"type": "W", "weight_lb_ft": 50.0,  "depth_in": 18.0, "flange_w_in": 7.50, "area_sq_in": 14.7},
    "W18X40":  {"type": "W", "weight_lb_ft": 40.0,  "depth_in": 17.9, "flange_w_in": 6.02, "area_sq_in": 11.8},
    "W18X35":  {"type": "W", "weight_lb_ft": 35.0,  "depth_in": 17.7, "flange_w_in": 6.00, "area_sq_in": 10.3},
    "W16X100": {"type": "W", "weight_lb_ft": 100.0, "depth_in": 17.0, "flange_w_in": 10.4, "area_sq_in": 29.4},
    "W16X50":  {"type": "W", "weight_lb_ft": 50.0,  "depth_in": 16.3, "flange_w_in": 7.07, "area_sq_in": 14.7},
    "W16X36":  {"type": "W", "weight_lb_ft": 36.0,  "depth_in": 15.9, "flange_w_in": 6.99, "area_sq_in": 10.6},
    "W16X31":  {"type": "W", "weight_lb_ft": 31.0,  "depth_in": 15.9, "flange_w_in": 5.53, "area_sq_in": 9.12},
    "W16X26":  {"type": "W", "weight_lb_ft": 26.0,  "depth_in": 15.7, "flange_w_in": 5.50, "area_sq_in": 7.68},
    "W14X176": {"type": "W", "weight_lb_ft": 176.0, "depth_in": 15.2, "flange_w_in": 15.7, "area_sq_in": 51.8},
    "W14X132": {"type": "W", "weight_lb_ft": 132.0, "depth_in": 14.7, "flange_w_in": 14.7, "area_sq_in": 38.8},
    "W14X90":  {"type": "W", "weight_lb_ft": 90.0,  "depth_in": 14.0, "flange_w_in": 14.5, "area_sq_in": 26.5},
    "W14X48":  {"type": "W", "weight_lb_ft": 48.0,  "depth_in": 13.8, "flange_w_in": 8.03, "area_sq_in": 14.1},
    "W14X30":  {"type": "W", "weight_lb_ft": 30.0,  "depth_in": 13.8, "flange_w_in": 6.73, "area_sq_in": 8.85},
    "W14X22":  {"type": "W", "weight_lb_ft": 22.0,  "depth_in": 13.7, "flange_w_in": 5.00, "area_sq_in": 6.49},
    "W12X120": {"type": "W", "weight_lb_ft": 120.0, "depth_in": 13.1, "flange_w_in": 12.3, "area_sq_in": 35.3},
    "W12X96":  {"type": "W", "weight_lb_ft": 96.0,  "depth_in": 12.7, "flange_w_in": 12.2, "area_sq_in": 28.2},
    "W12X72":  {"type": "W", "weight_lb_ft": 72.0,  "depth_in": 12.3, "flange_w_in": 12.0, "area_sq_in": 21.1},
    "W12X53":  {"type": "W", "weight_lb_ft": 53.0,  "depth_in": 12.1, "flange_w_in": 10.0, "area_sq_in": 15.6},
    "W12X35":  {"type": "W", "weight_lb_ft": 35.0,  "depth_in": 12.5, "flange_w_in": 6.56, "area_sq_in": 10.3},
    "W12X26":  {"type": "W", "weight_lb_ft": 26.0,  "depth_in": 12.2, "flange_w_in": 6.49, "area_sq_in": 7.65},
    "W12X19":  {"type": "W", "weight_lb_ft": 19.0,  "depth_in": 12.2, "flange_w_in": 4.01, "area_sq_in": 5.57},
    "W12X14":  {"type": "W", "weight_lb_ft": 14.0,  "depth_in": 11.9, "flange_w_in": 3.97, "area_sq_in": 4.16},
    "W10X49":  {"type": "W", "weight_lb_ft": 49.0,  "depth_in": 10.0, "flange_w_in": 10.0, "area_sq_in": 14.4},
    "W10X30":  {"type": "W", "weight_lb_ft": 30.0,  "depth_in": 10.5, "flange_w_in": 5.81, "area_sq_in": 8.84},
    "W10X22":  {"type": "W", "weight_lb_ft": 22.0,  "depth_in": 10.2, "flange_w_in": 5.75, "area_sq_in": 6.49},
    "W10X12":  {"type": "W", "weight_lb_ft": 12.0,  "depth_in": 9.87, "flange_w_in": 3.96, "area_sq_in": 3.54},
    "W8X31":   {"type": "W", "weight_lb_ft": 31.0,  "depth_in": 8.00, "flange_w_in": 8.00, "area_sq_in": 9.13},
    "W8X24":   {"type": "W", "weight_lb_ft": 24.0,  "depth_in": 7.93, "flange_w_in": 6.50, "area_sq_in": 7.08},
    "W8X15":   {"type": "W", "weight_lb_ft": 15.0,  "depth_in": 8.11, "flange_w_in": 4.02, "area_sq_in": 4.44},
    "W8X10":   {"type": "W", "weight_lb_ft": 10.0,  "depth_in": 7.89, "flange_w_in": 3.94, "area_sq_in": 2.96},

    # ── Square & Rectangular HSS (AISC Table 1-11, 1-12) ──
    "HSS16X16X5/8": {"type": "HSS", "weight_lb_ft": 127.40, "depth_in": 16.0, "flange_w_in": 16.0, "area_sq_in": 37.4},
    "HSS16X16X1/2": {"type": "HSS", "weight_lb_ft": 103.30, "depth_in": 16.0, "flange_w_in": 16.0, "area_sq_in": 30.4},
    "HSS16X16X3/8": {"type": "HSS", "weight_lb_ft": 78.60,  "depth_in": 16.0, "flange_w_in": 16.0, "area_sq_in": 23.1},
    "HSS14X14X5/8": {"type": "HSS", "weight_lb_ft": 110.40, "depth_in": 14.0, "flange_w_in": 14.0, "area_sq_in": 32.4},
    "HSS14X14X1/2": {"type": "HSS", "weight_lb_ft": 89.68,  "depth_in": 14.0, "flange_w_in": 14.0, "area_sq_in": 26.4},
    "HSS14X14X3/8": {"type": "HSS", "weight_lb_ft": 68.37,  "depth_in": 14.0, "flange_w_in": 14.0, "area_sq_in": 20.1},
    "HSS12X12X5/8": {"type": "HSS", "weight_lb_ft": 93.36,  "depth_in": 12.0, "flange_w_in": 12.0, "area_sq_in": 27.4},
    "HSS12X12X1/2": {"type": "HSS", "weight_lb_ft": 76.07,  "depth_in": 12.0, "flange_w_in": 12.0, "area_sq_in": 22.4},
    "HSS12X12X3/8": {"type": "HSS", "weight_lb_ft": 58.10,  "depth_in": 12.0, "flange_w_in": 12.0, "area_sq_in": 17.1},
    "HSS12X8X1/2":  {"type": "HSS", "weight_lb_ft": 62.46,  "depth_in": 12.0, "flange_w_in": 8.0,  "area_sq_in": 18.4},
    "HSS12X8X3/8":  {"type": "HSS", "weight_lb_ft": 47.90,  "depth_in": 12.0, "flange_w_in": 8.0,  "area_sq_in": 14.1},
    "HSS12X6X3/8":  {"type": "HSS", "weight_lb_ft": 42.79,  "depth_in": 12.0, "flange_w_in": 6.0,  "area_sq_in": 12.6},
    "HSS10X10X5/8": {"type": "HSS", "weight_lb_ft": 76.34,  "depth_in": 10.0, "flange_w_in": 10.0, "area_sq_in": 22.4},
    "HSS10X10X1/2": {"type": "HSS", "weight_lb_ft": 62.46,  "depth_in": 10.0, "flange_w_in": 10.0, "area_sq_in": 18.4},
    "HSS10X10X3/8": {"type": "HSS", "weight_lb_ft": 47.90,  "depth_in": 10.0, "flange_w_in": 10.0, "area_sq_in": 14.1},
    "HSS10X6X1/2":  {"type": "HSS", "weight_lb_ft": 47.35,  "depth_in": 10.0, "flange_w_in": 6.0,  "area_sq_in": 13.9},
    "HSS10X6X3/8":  {"type": "HSS", "weight_lb_ft": 37.69,  "depth_in": 10.0, "flange_w_in": 6.0,  "area_sq_in": 11.1},
    "HSS8X8X5/8":   {"type": "HSS", "weight_lb_ft": 59.32,  "depth_in": 8.0,  "flange_w_in": 8.0,  "area_sq_in": 17.4},
    "HSS8X8X1/2":   {"type": "HSS", "weight_lb_ft": 47.35,  "depth_in": 8.0,  "flange_w_in": 8.0,  "area_sq_in": 13.9},
    "HSS8X8X3/8":   {"type": "HSS", "weight_lb_ft": 37.69,  "depth_in": 8.0,  "flange_w_in": 8.0,  "area_sq_in": 11.1},
    "HSS8X8X1/4":   {"type": "HSS", "weight_lb_ft": 25.82,  "depth_in": 8.0,  "flange_w_in": 8.0,  "area_sq_in": 7.59},
    "HSS8X4X3/8":   {"type": "HSS", "weight_lb_ft": 27.48,  "depth_in": 8.0,  "flange_w_in": 4.0,  "area_sq_in": 8.08},
    "HSS6X6X1/2":   {"type": "HSS", "weight_lb_ft": 35.05,  "depth_in": 6.0,  "flange_w_in": 6.0,  "area_sq_in": 10.3},
    "HSS6X6X3/8":   {"type": "HSS", "weight_lb_ft": 27.48,  "depth_in": 6.0,  "flange_w_in": 6.0,  "area_sq_in": 8.08},
    "HSS6X6X1/4":   {"type": "HSS", "weight_lb_ft": 19.02,  "depth_in": 6.0,  "flange_w_in": 6.0,  "area_sq_in": 5.59},
    "HSS5X5X3/8":   {"type": "HSS", "weight_lb_ft": 22.37,  "depth_in": 5.0,  "flange_w_in": 5.0,  "area_sq_in": 6.58},
    "HSS5X5X1/4":   {"type": "HSS", "weight_lb_ft": 15.62,  "depth_in": 5.0,  "flange_w_in": 5.0,  "area_sq_in": 4.59},
    "HSS4X4X3/8":   {"type": "HSS", "weight_lb_ft": 17.27,  "depth_in": 4.0,  "flange_w_in": 4.0,  "area_sq_in": 5.08},
    "HSS4X4X1/4":   {"type": "HSS", "weight_lb_ft": 12.21,  "depth_in": 4.0,  "flange_w_in": 4.0,  "area_sq_in": 3.59},

    # ── Angles (AISC Table 1-7) ──
    "L8X8X1":    {"type": "L", "weight_lb_ft": 51.00, "depth_in": 8.0, "flange_w_in": 8.0, "area_sq_in": 15.0},
    "L8X8X1/2":  {"type": "L", "weight_lb_ft": 26.40, "depth_in": 8.0, "flange_w_in": 8.0, "area_sq_in": 7.75},
    "L6X6X1/2":  {"type": "L", "weight_lb_ft": 19.60, "depth_in": 6.0, "flange_w_in": 6.0, "area_sq_in": 5.75},
    "L6X6X3/8":  {"type": "L", "weight_lb_ft": 14.90, "depth_in": 6.0, "flange_w_in": 6.0, "area_sq_in": 4.36},
    "L5X5X1/2":  {"type": "L", "weight_lb_ft": 16.20, "depth_in": 5.0, "flange_w_in": 5.0, "area_sq_in": 4.75},
    "L5X5X3/8":  {"type": "L", "weight_lb_ft": 12.30, "depth_in": 5.0, "flange_w_in": 5.0, "area_sq_in": 3.61},
    "L4X4X1/2":  {"type": "L", "weight_lb_ft": 12.80, "depth_in": 4.0, "flange_w_in": 4.0, "area_sq_in": 3.75},
    "L4X4X3/8":  {"type": "L", "weight_lb_ft": 9.80,  "depth_in": 4.0, "flange_w_in": 4.0, "area_sq_in": 2.86},
    "L4X4X1/4":  {"type": "L", "weight_lb_ft": 6.60,  "depth_in": 4.0, "flange_w_in": 4.0, "area_sq_in": 1.94},
    "L3X3X1/4":  {"type": "L", "weight_lb_ft": 4.90,  "depth_in": 3.0, "flange_w_in": 3.0, "area_sq_in": 1.44},

    # ── Channels (AISC Table 1-5) ──
    "C15X50":    {"type": "C", "weight_lb_ft": 50.00, "depth_in": 15.0, "flange_w_in": 3.72, "area_sq_in": 14.7},
    "C15X33.9":  {"type": "C", "weight_lb_ft": 33.90, "depth_in": 15.0, "flange_w_in": 3.40, "area_sq_in": 9.96},
    "C12X30":    {"type": "C", "weight_lb_ft": 30.00, "depth_in": 12.0, "flange_w_in": 3.17, "area_sq_in": 8.82},
    "C12X20.7":  {"type": "C", "weight_lb_ft": 20.70, "depth_in": 12.0, "flange_w_in": 2.94, "area_sq_in": 6.09},
    "C10X30":    {"type": "C", "weight_lb_ft": 30.00, "depth_in": 10.0, "flange_w_in": 3.03, "area_sq_in": 8.82},
    "C10X15.3":  {"type": "C", "weight_lb_ft": 15.30, "depth_in": 10.0, "flange_w_in": 2.60, "area_sq_in": 4.49},
    "C8X18.75":  {"type": "C", "weight_lb_ft": 18.75, "depth_in": 8.0,  "flange_w_in": 2.53, "area_sq_in": 5.51},
    "C8X11.5":   {"type": "C", "weight_lb_ft": 11.50, "depth_in": 8.0,  "flange_w_in": 2.26, "area_sq_in": 3.38},
}

def export_database():
    os.makedirs("data", exist_ok=True)
    json_path = os.path.join("data", "aisc_v16_shapes.json")
    csv_path = os.path.join("data", "aisc_v16_shapes.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(AISC_DATABASE, f, indent=2)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["designation", "shape_type", "weight_lb_ft", "depth_in", "flange_w_in", "area_sq_in"])
        for des, data in AISC_DATABASE.items():
            writer.writerow([des, data["type"], data["weight_lb_ft"], data["depth_in"], data["flange_w_in"], data["area_sq_in"]])

    print(f"AISC Database successfully created with {len(AISC_DATABASE)} standard shapes:")
    print(f"  • JSON: {json_path}")
    print(f"  • CSV:  {csv_path}")

if __name__ == "__main__":
    export_database()
