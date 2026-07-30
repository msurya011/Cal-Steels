import json
import os
import re
import shutil
from pathlib import Path
from sklearn.model_selection import train_test_split


def normalize_filename(filename: str) -> str:
    """
    Normalize filename for robust matching:
    - Lowercase
    - Strip extension
    - Remove 'copy', 'page_N', 'rev'
    - Remove all non-alphanumeric characters
    """
    name = Path(filename).stem.lower()
    name = re.sub(r'(_copy(_\d+)?)+', '', name)
    name = re.sub(r'rev', '', name)
    name = re.sub(r'page_\d+', '', name)
    name = re.sub(r'page', '', name)
    name = re.sub(r'[^a-z0-9]', '', name)
    return name


def find_annotation_file(base_dir: Path = Path(".")) -> Path | None:
    """
    Auto-detect annotation JSON files in order of preference:
      1. annotations_detections.json
      2. annotations.json
      3. Any project-*.json or *.json file containing Label Studio task structures
    """
    candidates = [
        base_dir / "annotations_detections.json",
        base_dir / "annotations.json",
        base_dir.parent / "annotations_detections.json",
        base_dir.parent / "annotations.json",
    ]

    for cand in candidates:
        if cand.exists():
            return cand

    # Scan for any project-*.json or json files containing annotations
    for p in list(base_dir.glob("*.json")) + list(base_dir.parent.glob("*.json")):
        if p.name == "detection_results.json" or p.name == "data.yaml":
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0 and ("annotations" in data[0] or "file_upload" in data[0]):
                    return p
        except Exception:
            continue

    return None


def find_images_directory(base_dir: Path = Path(".")) -> Path | None:
    """
    Locates directory containing training images.
    Checks: imgs, images, datasets, drawing, drawings.
    """
    candidates = [
        base_dir / "imgs",
        base_dir / "images",
        base_dir / "datasets",
        base_dir / "drawing",
        base_dir / "drawings",
        base_dir.parent / "imgs",
    ]
    for c in candidates:
        if c.exists() and c.is_dir() and any(c.glob("*.*")):
            return c
    return None


def find_image(images_dir: Path, filename: str):
    """
    Try multiple strategies to locate an image:
    1. Exact match
    2. Normalized match
    3. Partial / Substring match
    """
    p = images_dir / filename
    if p.exists():
        return p, filename

    target = normalize_filename(filename)

    if not hasattr(find_image, "_cache") or find_image._cache_dir != images_dir:
        find_image._cache_dir = images_dir
        find_image._cache = {normalize_filename(f.name): f for f in images_dir.iterdir() if f.is_file()}

    if target in find_image._cache:
        res = find_image._cache[target]
        return res, res.name

    for cache_name, res in find_image._cache.items():
        if len(target) > 4 and (target in cache_name or cache_name in target):
            return res, res.name

    return None, None


def extract_classes_from_annotations(annotation_data: list) -> list[str]:
    """
    Dynamically extracts all unique label names from Label Studio annotations.
    Includes title block labels or structural symbols if present in annotations.
    """
    classes = set()

    for task in annotation_data:
        for ann in task.get("annotations", []):
            for res in ann.get("result", []):
                val = res.get("value", {})
                for key in ["labels", "rectanglelabels"]:
                    if key in val:
                        for label_name in val[key]:
                            if label_name:
                                classes.add(label_name)

    if not classes:
        # Fallback default title block if no annotated classes found
        default_title_block = ["REVISION_TABLE", "DRAWING_NO", "DRAWING_DESCRIPTION", "PROJECT_NO"]
        for dtb in default_title_block:
            classes.add(dtb)

    return sorted(list(classes))


def convert_ls_to_yolo(annotation_file: str | Path | None = None, images_dir: str | Path | None = None):
    base_dir = Path(".").resolve()

    # Auto-detect annotation file
    if annotation_file is None:
        ann_path = find_annotation_file(base_dir)
    else:
        ann_path = Path(annotation_file).resolve()

    if not ann_path or not ann_path.exists():
        print(f"ERROR: Annotation file not found. Place 'annotations_detections.json' or 'annotations.json' in {base_dir}")
        return False

    print(f"[ANN] Found Annotation File: {ann_path}")

    # Auto-detect image directory
    if images_dir is None:
        img_path = find_images_directory(base_dir)
    else:
        img_path = Path(images_dir).resolve()

    if not img_path or not img_path.exists():
        print(f"ERROR: Images directory not found in {base_dir}. Place images in 'imgs/' or 'images/' folder.")
        return False

    print(f"[IMG] Found Images Directory: {img_path}")

    with open(ann_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Dynamically extract classes
    classes = extract_classes_from_annotations(data)
    cls_to_id = {cls: i for i, cls in enumerate(classes)}
    print(f"[CLS] Detected {len(classes)} classes: {classes}")

    output_dataset_dir = base_dir / "datasets" / "drawings"

    # Clean & recreate split directories
    for split in ['train', 'val']:
        for sub in ['images', 'labels']:
            d = output_dataset_dir / sub / split
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)

    valid_tasks = []
    skipped = []

    for task in data:
        if not task.get('annotations'):
            skipped.append((task.get('file_upload', '?'), 'no annotations'))
            continue

        full_filename = task.get('file_upload', '')
        if not full_filename and 'data' in task and 'image' in task['data']:
            full_filename = Path(task['data']['image']).name

        parts = full_filename.split('-', 1)
        original_filename = parts[1] if len(parts) > 1 else full_filename

        src_img, resolved_name = find_image(img_path, original_filename)

        if src_img is None:
            skipped.append((original_filename, 'image not found in image directory'))
            continue

        dest_name = original_filename.replace(' ', '_')
        valid_tasks.append((task, src_img, dest_name))

    print(f"Valid tasks : {len(valid_tasks)}")
    print(f"Skipped     : {len(skipped)}")
    if skipped:
        print("\nSkipped entries:")
        for name, reason in skipped[:10]:
            print(f"  {name}  [{reason}]")
        if len(skipped) > 10:
            print(f"  ... and {len(skipped) - 10} more.")

    if not valid_tasks:
        print("\nERROR: No valid tasks matched with local images.")
        return False

    if len(valid_tasks) < 2:
        train_tasks, val_tasks = valid_tasks, []
    else:
        train_tasks, val_tasks = train_test_split(
            valid_tasks, test_size=0.2, random_state=42
        )

    def process_split(tasks, split):
        count = 0
        for task, src_img, dest_name in tasks:
            dest_img = output_dataset_dir / "images" / split / dest_name
            shutil.copy(src_img, dest_img)

            label_path = output_dataset_dir / "labels" / split / (Path(dest_name).stem + ".txt")
            with open(label_path, 'w', encoding='utf-8') as lf:
                for ann in task.get('annotations', [])[0].get('result', []):
                    if ann.get('type') not in ['labels', 'rectanglelabels']:
                        continue
                    val = ann.get('value', {})
                    label_key = 'labels' if 'labels' in val else 'rectanglelabels'
                    labels_list = val.get(label_key, [])
                    if not labels_list or labels_list[0] not in cls_to_id:
                        continue

                    label = labels_list[0]
                    cls_id = cls_to_id[label]

                    x_perc = val['x']
                    y_perc = val['y']
                    w_perc = val['width']
                    h_perc = val['height']

                    x_center = (x_perc + w_perc / 2) / 100
                    y_center = (y_perc + h_perc / 2) / 100
                    width = w_perc / 100
                    height = h_perc / 100

                    lf.write(f"{cls_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}\n")
            count += 1
        return count

    train_count = process_split(train_tasks, 'train')
    val_count = process_split(val_tasks, 'val')

    print(f"\n[OK] Dataset ready at: {output_dataset_dir}")
    print(f"  train : {train_count} images + labels")
    print(f"  val   : {val_count} images + labels")

    # Generate data.yaml
    names_yaml = "\n".join([f"  {i}: {cls_name}" for i, cls_name in enumerate(classes)])
    yaml_content = f"""path: {output_dataset_dir.as_posix()}
train: images/train
val: images/val

nc: {len(classes)}
names:
{names_yaml}
"""
    yaml_path = base_dir / "data.yaml"
    with open(yaml_path, 'w', encoding='utf-8') as f:
        f.write(yaml_content)

    print(f"[OK] data.yaml written to: {yaml_path.resolve()}\n")
    return True


if __name__ == "__main__":
    convert_ls_to_yolo()
