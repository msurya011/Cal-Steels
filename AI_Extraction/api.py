from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os
import tempfile
from pathlib import Path
from inference import get_latest_model, setup_predictor, process_pdf, get_class_names
from extraction import process_extracted_data
from prepare_dataset import convert_ls_to_yolo, find_annotation_file
from train import train_yolo

app = FastAPI(title="SteelGenie AI Extraction API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global model instance
model = None
model_file_path = None


def load_active_model():
    """Auto-detects and loads the latest trained model weights."""
    global model, model_file_path
    try:
        model_path = get_latest_model()
        if model_path and model_path.exists():
            model = setup_predictor(str(model_path))
            model_file_path = str(model_path)
            print(f"[API] Successfully loaded AI model from: {model_file_path}")
            return True
    except Exception as e:
        print(f"[API Warning] Could not load model: {e}")
    return False


# Load model at startup
load_active_model()


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "SteelGenie AI Extraction Service",
        "model_loaded": model is not None,
        "model_path": model_file_path
    }


@app.get("/status")
def get_status():
    ann_file = find_annotation_file()
    classes = get_class_names(model) if model else []
    return {
        "model_loaded": model is not None,
        "model_path": model_file_path,
        "annotation_file": str(ann_file) if ann_file else None,
        "detected_classes": classes
    }


@app.post("/upload")
async def extract_data(files: list[UploadFile] = File(...)):
    """
    Endpoint called whenever the user uploads new PDFs for detection.
    Processes PDF files with the active AI model and returns structured detections.
    """
    global model
    if not model:
        # Try reloading model dynamically
        if not load_active_model():
            return {"error": "AI Model not loaded properly or missing weights."}

    results = {}

    for idx, file in enumerate(files):
        print(f"[{idx+1}/{len(files)}] Processing uploaded PDF: {file.filename}...")
        temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(temp_fd)

        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        try:
            # Perform AI extraction on PDF
            raw_results = process_pdf(temp_path, model, original_filename=file.filename)

            # Format extracted data cleanly
            formatted_data = process_extracted_data(raw_results)
            results[file.filename] = formatted_data
            print(f"  -> Successfully extracted {len(raw_results)} regions in {file.filename}")
        except Exception as e:
            print(f"  -> Error processing {file.filename}: {e}")
            results[file.filename] = {"error": str(e)}
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    return results


@app.post("/train")
def trigger_training(background_tasks: BackgroundTasks, epochs: int = 80):
    """
    Triggers dataset preparation and YOLO model retraining/fine-tuning.
    """
    def run_training_pipeline():
        print("[API] Starting auto-dataset conversion...")
        if convert_ls_to_yolo():
            print("[API] Starting YOLO model fine-tuning...")
            new_model_path = train_yolo(epochs=epochs)
            if new_model_path:
                print("[API] Training finished. Reloading active AI model...")
                load_active_model()

    background_tasks.add_task(run_training_pipeline)
    return {
        "status": "started",
        "message": "Dataset preparation and model fine-tuning started in background."
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
