"""
Extraction Helper Module
========================
Formats raw AI bounding box detections into clean structured JSON responses.
"""

from typing import Any, Dict, List


def process_extracted_data(file_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Processes raw detection objects from `process_pdf` into a structured dictionary.

    Categorizes detections into:
      - title_block: Key metadata fields (DRAWING_NO, PROJECT_NO, DRAWING_DESCRIPTION, REVISION_TABLE)
      - structural_elements: Member symbols (I-Column, Cube-Column, etc.)
      - raw_detections: List of all raw detection items
    """
    structured_output: Dict[str, Any] = {
        "title_block": {},
        "structural_elements": [],
        "raw_detections": file_results or []
    }

    title_block_keys = {"REVISION_TABLE", "DRAWING_NO", "DRAWING_DESCRIPTION", "PROJECT_NO"}

    for item in file_results or []:
        label = item.get("label", "")
        if label in title_block_keys:
            structured_output["title_block"][label] = {
                "text": item.get("text", "").strip(),
                "confidence": item.get("confidence", 0.0),
                "box": item.get("box"),
                "rows": item.get("rows"),
                "page": item.get("page", 0),
                "note": item.get("note")
            }
        else:
            structured_output["structural_elements"].append({
                "label": label,
                "confidence": item.get("confidence", 0.0),
                "box": item.get("box"),
                "page": item.get("page", 0)
            })

    return structured_output
