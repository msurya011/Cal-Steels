import os
import shutil
from pathlib import Path
from ultralytics import YOLO
from prepare_dataset import convert_ls_to_yolo


def clear_label_caches(dataset_dir: Path):
    """Removes cached .cache files to force dataset label re-indexing."""
    if not dataset_dir.exists():
        return
    for cache_file in dataset_dir.glob("**/*.cache"):
        try:
            cache_file.unlink()
            print(f"[Cache] Cleared dataset label cache: {cache_file.name}")
        except Exception:
            pass


def get_fresh_model(weights_name: str = "yolo11n.pt") -> YOLO:
    """
    Creates a fresh YOLO model instance initialized from pretrained weights.
    """
    base_dir = Path(".").resolve()
    w_path = base_dir / weights_name
    if w_path.exists():
        print(f"[Fine-tune] Initializing model from: {w_path}")
        return YOLO(str(w_path))

    print(f"[Fine-tune] Initializing fresh pretrained model '{weights_name}'")
    return YOLO(weights_name)


def train_yolo(epochs: int = 20, batch_size: int = 4):
    base_dir = Path(".").resolve()
    yaml_path = base_dir / "data.yaml"

    print("[Dataset] Syncing dataset annotations and generating data.yaml...")
    success = convert_ls_to_yolo()
    if not success or not yaml_path.exists():
        print("ERROR: Failed to prepare dataset from annotations.")
        return None

    # Clear old dataset label caches before training
    dataset_dir = base_dir / "datasets" / "drawings"
    clear_label_caches(dataset_dir)

    model = get_fresh_model("yolo11n.pt")

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[Device] Training on: {device.upper()}")

    results = model.train(
        data=str(yaml_path),
        epochs=epochs,
        patience=20,
        imgsz=1280,
        batch=batch_size,
        device=device,
        workers=0,
        project=str(base_dir / "runs" / "detect"),
        name="finetune",
        exist_ok=True,
        plots=True,
        verbose=True,
        lr0=0.001,
        lrf=0.01,
        single_cls=False,
        rect=True,
        degrees=8.0,
        translate=0.08,
        scale=0.15,
        flipud=0.0,
        fliplr=0.0,
        mosaic=0.2,
        close_mosaic=10,
    )

    possible_weights = [
        base_dir / "runs" / "detect" / "finetune" / "weights" / "best.pt",
        base_dir / "runs" / "detect" / "runs" / "detect" / "finetune" / "weights" / "best.pt",
    ]
    
    best_weights = None
    for pw in possible_weights:
        if pw.exists():
            best_weights = pw
            break

    if best_weights and best_weights.exists():
        root_best = base_dir / "best.pt"
        shutil.copy(best_weights, root_best)
        print(f"\n[OK] Training complete. Best model saved to:\n  - {best_weights}\n  - {root_best}")
        return root_best

    return None


if __name__ == "__main__":
    train_yolo()