from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import numpy as np


def _clean_ocr_text(text: str) -> str:
    """Normalize whitespace and common OCR artifacts."""
    t = re.sub(r"[ \t]+", " ", text)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


_reader: Any = None
_reader_lock = threading.Lock()


def _get_reader() -> Any:
    """Return the process-wide EasyOCR reader, initialized lazily on first use.

    EasyOCR loads ~200MB of model weights (2-5s on CPU), so we keep one Reader
    per worker process for its entire lifetime. GPU is enabled when the
    EASYOCR_GPU env var is truthy and CUDA is available; otherwise CPU is used.
    """
    global _reader
    if _reader is not None:
        return _reader
    with _reader_lock:
        if _reader is None:
            import easyocr

            use_gpu = os.getenv("EASYOCR_GPU", "false").strip().lower() in (
                "true",
                "1",
                "yes",
                "on",
            )
            _reader = easyocr.Reader(["fr", "en"], gpu=use_gpu, verbose=False)
    return _reader


def ocr_pdf_pages(file_path: Path, *, dpi: int, min_chars: int = 50) -> tuple[str, str]:
    """Rasterize sparse PDF pages and OCR with EasyOCR (fra+eng).

    Args:
        file_path: Path to PDF.
        dpi: Rasterization DPI (e.g. 200).
        min_chars: If native text per page has fewer characters, run OCR.

    Returns:
        Tuple of (combined_text, extraction_method) where method is ``ocr_easyocr``
        if any page used OCR, otherwise ``text_extraction``.
    """
    doc = fitz.open(file_path)
    parts: list[str] = []
    used_ocr = False
    reader: Any = None
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    try:
        for page in doc:
            native = page.get_text("text") or ""
            if len(native.strip()) >= min_chars:
                parts.append(native.strip())
                continue
            used_ocr = True
            if reader is None:
                reader = _get_reader()
            pix = page.get_pixmap(matrix=mat, alpha=False)
            h, w = pix.height, pix.width
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(h, w, pix.n)
            if pix.n == 4:
                img = img[:, :, :3]
            lines = reader.readtext(img, detail=0, paragraph=True)
            block = "\n".join(lines) if lines else ""
            parts.append(block.strip())
    finally:
        doc.close()

    text = _clean_ocr_text("\n\n".join(p for p in parts if p))
    method = "ocr_easyocr" if used_ocr else "text_extraction"
    return text, method
