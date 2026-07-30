import cv2
import fitz
import json
import os
import re
import argparse
from pathlib import Path
from ultralytics import YOLO
import numpy as np


def setup_predictor(model_path):
    """Loads a YOLO model from file path."""
    return YOLO(model_path)


def normalize_canvas(img, target_size=1280):
    """
    Resizes image to target_size using letterboxing (maintaining aspect ratio with padding).
    Returns: padded_image, scale_used, padding_x, padding_y
    """
    h, w = img.shape[:2]
    scale = min(target_size / h, target_size / w)
    nh, nw = int(h * scale), int(w * scale)
    img_resized = cv2.resize(img, (nw, nh))

    canvas = np.full((target_size, target_size, 3), 128, dtype=np.uint8)
    dx = (target_size - nw) // 2
    dy = (target_size - nh) // 2
    canvas[dy : dy + nh, dx : dx + nw] = img_resized

    return canvas, scale, dx, dy


def get_latest_model(project_prefix: str | None = None) -> Path:
    """
    Auto-detects the best trained model weights available.
    Search order:
      1. Explicit fine-tuned model (runs/detect/finetune/weights/best.pt)
      2. Root 'best.pt'
      3. Project-prefix specific model (if provided)
      4. Latest train* run weights
      5. Base models (yolo26n.pt, yolo11s.pt, yolo11n.pt)
    """
    base_dir = Path(".").resolve()

    # 1. Fine-tuned model candidates
    finetune_candidates = [
        base_dir / "best.pt",
        base_dir / "runs" / "detect" / "finetune" / "weights" / "best.pt",
        base_dir / "runs" / "detect" / "runs" / "detect" / "finetune" / "weights" / "best.pt",
    ]
    existing = [fc for fc in finetune_candidates if fc.exists()]
    if existing:
        latest = max(existing, key=lambda f: f.stat().st_mtime)
        print(f"[Model] Using fine-tuned model: {latest}")
        return latest

    # 3. Project prefix model
    if project_prefix:
        p_path = base_dir / "runs" / "detect" / "finetune" / "weights" / f"{project_prefix}_best.pt"
        if p_path.exists():
            print(f"[Model] Using project-specific model: {p_path}")
            return p_path

    # 4. Search最新 train* runs
    runs_dir = base_dir / "runs" / "detect"
    if runs_dir.exists():
        def get_run_num(p):
            match = re.search(r'train(\d*)', p.name)
            return int(match.group(1)) if match and match.group(1) else 0

        latest_runs = sorted(
            [d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("train")],
            key=get_run_num,
            reverse=True
        )

        for run in latest_runs:
            for weight_name in ["best.pt", "last.pt"]:
                if project_prefix:
                    candidates = [f"{project_prefix}_{weight_name}", weight_name]
                else:
                    candidates = [weight_name]

                for c_name in candidates:
                    potential_weight = run / "weights" / c_name
                    if potential_weight.exists():
                        print(f"[Model] Using run model: {potential_weight}")
                        return potential_weight

    # 5. Base model fallbacks
    for base_name in ["yolo26n.pt", "yolo11s.pt", "yolo11n.pt"]:
        base_path = base_dir / base_name
        if base_path.exists():
            print(f"[Model] Using base model: {base_path}")
            return base_path

    # Default download fallback
    print("[Model] Fallback to loading default 'yolo11s.pt'")
    return Path("yolo11s.pt")


def get_class_names(model) -> list[str]:
    """Gets class names dictionary/list from model or data.yaml."""
    if hasattr(model, "names") and model.names:
        if isinstance(model.names, dict):
            return [model.names[i] for i in sorted(model.names.keys())]
        return list(model.names)

    yaml_path = Path("data.yaml")
    if yaml_path.exists():
        try:
            import yaml
            with open(yaml_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
                if content and "names" in content:
                    names = content["names"]
                    if isinstance(names, dict):
                        return [names[i] for i in sorted(names.keys())]
                    return list(names)
        except Exception:
            pass

    return ["Cube-Column", "I-Column"]


def process_pdf(pdf_path, model=None, original_filename=None):
    """
    Performs AI object detection & text extraction on a PDF file.
    """
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if model is None:
        model_path = get_latest_model()
        model = setup_predictor(str(model_path))

    class_names = get_class_names(model)

    doc = fitz.open(pdf_path)
    best_detections = {}
    all_detections = []

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"

    max_pages = len(doc)

    for i in range(max_pages):
        page = doc[i]
        pix = page.get_pixmap(dpi=150)

        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        else:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        norm_img, scale_val, dx, dy = normalize_canvas(img, target_size=1280)

        prediction_results = model.predict(norm_img, imgsz=1280, conf=0.015, verbose=False, device=device)

        for r in prediction_results:
            boxes = r.boxes
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cls = int(box.cls[0].item())
                score = float(box.conf[0].item())

                label = class_names[cls] if cls < len(class_names) else f"class_{cls}"

                # Coordinates translation back to original image
                x1_orig = (x1 - dx) / scale_val
                y1_orig = (y1 - dy) / scale_val
                x2_orig = (x2 - dx) / scale_val
                y2_orig = (y2 - dy) / scale_val

                # PDF coordinates (72 dpi) from image coordinates (150 dpi)
                scale_to_pdf = 72 / 150
                pdf_box = [x1_orig * scale_to_pdf, y1_orig * scale_to_pdf,
                           x2_orig * scale_to_pdf, y2_orig * scale_to_pdf]

                text = page.get_textbox(pdf_box)
                rows = []
                if label == "REVISION_TABLE":
                    blocks = page.get_text("blocks", clip=pdf_box)
                    blocks.sort(key=lambda b: (b[1], b[0]))
                    current_row = []
                    last_y = -1
                    threshold = 5
                    header_keywords = {"REV", "DESCRIPTION", "DATE", "DWN", "CHKD", "APPROV", "REVISION", "REVISIONS"}

                    for b in blocks:
                        txt = b[4].strip()
                        if not txt: continue
                        txt_upper = txt.upper()
                        clean_txt = "".join(c if c.isalnum() or c.isspace() else " " for c in txt_upper)
                        words = set(clean_txt.split())
                        match_count = len(words.intersection(header_keywords))
                        is_header = match_count >= 2 or (match_count >= 1 and len(txt) < 15)

                        if is_header and len(txt) < 60:
                            continue

                        if last_y == -1 or abs(b[1] - last_y) < threshold:
                            current_row.append(txt)
                        else:
                            rows.append(current_row)
                            current_row = [txt]
                        last_y = b[1]
                    if current_row:
                        rows.append(current_row)

                elif label in ["PROJECT_NO", "DRAWING_NO", "DRAWING_DESCRIPTION"]:
                    rows = [[line.strip()] for line in text.split('\n') if line.strip()]

                detection_data = {
                    "page": i,
                    "label": label,
                    "confidence": score,
                    "box": [x1_orig, y1_orig, x2_orig, y2_orig],
                    "pdf_box": pdf_box,
                    "text": text.strip(),
                    "rows": rows if rows else None
                }

                all_detections.append(detection_data)

    doc.close()

    valid_labels = set(class_names)
    final_output = [det for det in all_detections if det["label"] in valid_labels]
    return final_output


def process_path(input_path: str | Path, model=None, output_file: str = "detection_results.json"):
    """
    Processes a single PDF file or an entire directory of PDFs.
    """
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        print(f"Error: Input path '{input_path}' does not exist.")
        return {}

    if model is None:
        model_path = get_latest_model()
        print(f"[Inference] Loading model: {model_path}")
        model = setup_predictor(str(model_path))

    results = {}

    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        print(f"[PDF] Processing single file: {input_path.name}")
        pdf_res = process_pdf(input_path, model, original_filename=input_path.name)
        results[input_path.name] = pdf_res
    elif input_path.is_dir():
        pdf_files = sorted(list(set(input_path.glob("*.pdf")).union(set(input_path.glob("*.PDF")))))
        print(f"[PDF] Found {len(pdf_files)} PDF file(s) in {input_path.name}")
        for pdf_file in pdf_files:
            print(f"  -> Processing {pdf_file.name}...")
            pdf_res = process_pdf(pdf_file, model, original_filename=pdf_file.name)
            results[pdf_file.name] = pdf_res
    else:
        print(f"Error: '{input_path}' is not a valid PDF file or directory.")
        return {}

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4)
        print(f"[OK] Results saved to: {output_file}")

    return results


def main():
    parser = argparse.ArgumentParser(description="AI Extraction Inference on Engineering PDF Drawings.")
    parser.add_argument("input_path", nargs="?", default=None, help="Path to PDF file or folder containing PDFs.")
    parser.add_argument("--model", default=None, help="Custom path to trained YOLO .pt model weights.")
    parser.add_argument("--output", default="detection_results.json", help="Output JSON results file.")

    args = parser.parse_args()

    # Determine input path
    if args.input_path:
        target_path = Path(args.input_path)
    else:
        # Auto-discover PDF folders in workspace
        possible_dirs = ["drawings", "drawing", "pdf's", "pdfs", "."]
        target_path = None
        for pd in possible_dirs:
            p = Path(pd)
            if p.exists() and (p.is_file() or len(list(p.glob("*.pdf"))) > 0):
                target_path = p
                break

    if not target_path or not target_path.exists():
        print("Error: No PDF files or directories found. Please specify input path: python inference.py path/to/pdf")
        return

    model_instance = setup_predictor(args.model) if args.model else None
    process_path(target_path, model=model_instance, output_file=args.output)


if __name__ == "__main__":
    main()