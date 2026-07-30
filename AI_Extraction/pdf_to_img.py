"""
PDF to Image Converter
=======================
Converts every page of a PDF file into a separate image (e.g., 10 pages -> 10 pictures).

Usage:
  - Command Line:
      python pdf_to_img.py path/to/file.pdf [output_dir] [--dpi 300] [--format png]
      python pdf_to_img.py path/to/folder_with_pdfs/

  - Python Import:
      from pdf_to_img import convert_pdf_to_images
      images = convert_pdf_to_images("document.pdf", output_dir="output_images")
"""

import os
import sys
import argparse
from pathlib import Path

try:
    import fitz  # PyMuPDF
    HAVE_FITZ = True
except ImportError:
    HAVE_FITZ = False

try:
    from pdf2image import convert_from_path
    HAVE_PDF2IMAGE = True
except ImportError:
    HAVE_PDF2IMAGE = False


def convert_pdf_to_images(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
    dpi: int = 300,
    fmt: str = "png"
) -> list[str]:
    """
    Converts each page of a PDF file into a separate image file.

    :param pdf_path: Path to the input PDF file.
    :param output_dir: Directory where output images will be saved.
                       If None, saves in a subfolder named after the PDF.
    :param dpi: Image resolution in dots per inch (default: 300 DPI for high quality).
    :param fmt: Output image format ('png', 'jpg', 'jpeg', 'webp').
    :return: List of absolute file paths to created images.
    """
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    # Determine output directory
    if output_dir is None:
        output_dir = pdf_path.parent / f"{pdf_path.stem}_images"
    else:
        output_dir = Path(output_dir).resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower().lstrip(".")

    saved_images: list[str] = []

    if HAVE_FITZ:
        # High-performance PyMuPDF rendering
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        print(f"[PDF] Processing '{pdf_path.name}' ({total_pages} page{'s' if total_pages != 1 else ''})...")

        # DPI zoom matrix (72 DPI is standard baseline in PDF)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=matrix, alpha=False)

            # Pad page numbers (e.g. page_001.png for 10+ pages)
            pad_width = max(3, len(str(total_pages)))
            image_filename = f"{pdf_path.stem}_page_{page_num + 1:0{pad_width}d}.{fmt}"
            image_path = output_dir / image_filename

            pix.save(str(image_path))
            saved_images.append(str(image_path))
            print(f"  -> Saved Page {page_num + 1}/{total_pages}: {image_filename}")

        doc.close()

    elif HAVE_PDF2IMAGE:
        # Fallback to pdf2image
        print(f"[PDF] Converting '{pdf_path.name}' using pdf2image...")
        images = convert_from_path(str(pdf_path), dpi=dpi)
        total_pages = len(images)

        for page_num, img in enumerate(images, start=1):
            pad_width = max(3, len(str(total_pages)))
            image_filename = f"{pdf_path.stem}_page_{page_num:0{pad_width}d}.{fmt}"
            image_path = output_dir / image_filename

            img.save(str(image_path), format=fmt.upper())
            saved_images.append(str(image_path))
            print(f"  -> Saved Page {page_num}/{total_pages}: {image_filename}")

    else:
        raise ImportError(
            "No PDF processing library available. Please install PyMuPDF: pip install PyMuPDF"
        )

    print(f"[OK] Finished! {len(saved_images)} image(s) saved to: {output_dir}\n")
    return saved_images


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF pages to individual images (10 pages = 10 pictures)."
    )
    parser.add_argument("input_path", nargs="?", default=None, help="Path to a PDF file or directory containing PDFs.")
    parser.add_argument("output_dir", nargs="?", default=None, help="Directory to save output images.")
    parser.add_argument("--dpi", type=int, default=300, help="Image resolution in DPI (default: 300).")
    parser.add_argument("--format", default="png", choices=["png", "jpg", "jpeg", "webp"], help="Image format (default: png).")

    args = parser.parse_args()

    if args.input_path:
        target_path = Path(args.input_path).resolve()
    else:
        # Auto-discover PDF folders in workspace (prioritizing pdf's)
        candidates = ["pdf's", "pdfs", "drawings", "drawing", "."]
        target_path = None
        for cand in candidates:
            p = Path(cand).resolve()
            if p.exists() and (p.is_file() or len(list(p.glob("*.pdf")) + list(p.glob("*.PDF"))) > 0):
                target_path = p
                print(f"[Auto-discover] Using input path: {p}")
                break

    if not target_path or not target_path.exists():
        print("Error: No PDF files or directories found. Specify input path: python pdf_to_img.py path/to/pdf")
        return

    if target_path.is_file() and target_path.suffix.lower() == ".pdf":
        convert_pdf_to_images(target_path, args.output_dir, dpi=args.dpi, fmt=args.format)
    elif target_path.is_dir():
        pdf_files = sorted(list(set(target_path.glob("*.pdf")).union(set(target_path.glob("*.PDF")))))
        if not pdf_files:
            print(f"No PDF files found in directory: {target_path}")
            return
        print(f"Found {len(pdf_files)} PDF file(s) in {target_path.name}\n")
        for pdf_file in pdf_files:
            convert_pdf_to_images(pdf_file, args.output_dir, dpi=args.dpi, fmt=args.format)
    else:
        print(f"Error: Invalid input path '{target_path}'. Must be a PDF file or directory.")


if __name__ == "__main__":
    main()
