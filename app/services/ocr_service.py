from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import numpy as np

from app.utils.metrics import cv_ocr_fallback_total, ocr_duration_seconds


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
            kwargs: dict[str, Any] = {"gpu": use_gpu, "verbose": False}
            model_dir = os.getenv("EASYOCR_MODULE_PATH")
            if model_dir:
                kwargs["model_storage_directory"] = model_dir
                kwargs["download_enabled"] = False
            _reader = easyocr.Reader(["fr", "en"], **kwargs)
    return _reader


def _boxes_to_text(results: list[Any]) -> str:
    """Reconstruct line-structured text from EasyOCR ``detail=1`` results.

    EasyOCR returns one entry per detected text box as ``(bbox, text, conf)``,
    where ``bbox`` is four ``[x, y]`` corner points. The previous
    ``paragraph=True`` mode merged visually-adjacent boxes into blocks, which
    destroyed the line breaks the downstream PII/section logic depends on (a
    merged header line exceeds the contact-block length cutoff, so the name is
    never found). Here we instead rebuild lines: group boxes by vertical
    position (new line when the gap to the previous box exceeds ~0.6x the median
    box height), order each line left-to-right, and join lines with ``\\n`` — so
    OCR output reads like native PDF text regardless of CV template.
    """
    boxes: list[tuple[float, float, float, str]] = []
    for entry in results:
        if not entry:
            continue
        bbox, text = entry[0], entry[1]
        s = str(text).strip()
        if not s:
            continue
        ys = [float(pt[1]) for pt in bbox]
        xs = [float(pt[0]) for pt in bbox]
        y_center = sum(ys) / len(ys)
        boxes.append((y_center, min(xs), max(ys) - min(ys), s))

    if not boxes:
        return ""

    boxes.sort(key=lambda b: b[0])  # top-to-bottom by vertical center
    heights = sorted(b[2] for b in boxes if b[2] > 0)
    median_h = heights[len(heights) // 2] if heights else 0.0
    threshold = 0.6 * median_h  # 0.0 when degenerate → every distinct row splits

    lines: list[list[tuple[float, str]]] = []
    current: list[tuple[float, str]] = []
    prev_y: float | None = None
    for y_center, x_left, _h, s in boxes:
        if prev_y is not None and (y_center - prev_y) > threshold:
            lines.append(current)
            current = []
        current.append((x_left, s))
        prev_y = y_center
    if current:
        lines.append(current)

    out: list[str] = []
    for line in lines:
        line.sort(key=lambda t: t[0])  # left-to-right
        out.append(" ".join(t[1] for t in line))
    return "\n".join(out)


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

    start = time.perf_counter()
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
            results = reader.readtext(img, detail=1, paragraph=False)
            block = _boxes_to_text(results)
            parts.append(block.strip())
    finally:
        doc.close()

    ocr_duration_seconds.observe(time.perf_counter() - start)
    if used_ocr:
        cv_ocr_fallback_total.inc()

    text = _clean_ocr_text("\n\n".join(p for p in parts if p))
    method = "ocr_easyocr" if used_ocr else "text_extraction"
    return text, method
