"""Tests for OCR line reconstruction (`_boxes_to_text`).

These exercise the pure box-grouping helper with synthetic EasyOCR
``detail=1`` results, so no EasyOCR model or image is required.
"""

from __future__ import annotations

from app.services.ocr_service import _boxes_to_text


def _box(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    """EasyOCR-style 4-point bbox: TL, TR, BR, BL."""
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_empty_results_returns_empty_string() -> None:
    assert _boxes_to_text([]) == ""


def test_reconstructs_lines_top_to_bottom() -> None:
    # Deliberately out of vertical order — must be sorted top-to-bottom.
    results = [
        (_box(10, 30, 250, 52), "Process Engineer", 0.95),
        (_box(10, 2, 200, 24), "Nicole Moore", 0.99),
    ]
    assert _boxes_to_text(results) == "Nicole Moore\nProcess Engineer"


def test_same_row_boxes_joined_left_to_right() -> None:
    # Two boxes on the same row, provided right-then-left.
    results = [
        (_box(420, 60, 600, 85), "+1 971 902 4932", 0.9),
        (_box(10, 60, 400, 85), "nicole.moore@gmail.com", 0.9),
    ]
    assert _boxes_to_text(results) == "nicole.moore@gmail.com +1 971 902 4932"


def test_full_header_kept_as_separate_lines() -> None:
    # The exact failure mode: name/title/contact must NOT collapse into one line.
    results = [
        (_box(10, 2, 200, 24), "Nicole Moore", 0.99),
        (_box(10, 30, 250, 52), "Process Engineer", 0.95),
        (_box(10, 60, 400, 85), "nicole.moore@gmail.com", 0.9),
    ]
    out = _boxes_to_text(results)
    assert out.split("\n")[0] == "Nicole Moore"
    assert out.split("\n") == [
        "Nicole Moore",
        "Process Engineer",
        "nicole.moore@gmail.com",
    ]


def test_blank_text_boxes_skipped() -> None:
    results = [
        (_box(10, 2, 200, 24), "Nicole Moore", 0.99),
        (_box(10, 30, 250, 52), "   ", 0.4),
        (_box(10, 60, 200, 82), "Engineer", 0.9),
    ]
    assert _boxes_to_text(results) == "Nicole Moore\nEngineer"


def test_slightly_misaligned_boxes_stay_on_same_row() -> None:
    # Real OCR rows wobble a few px vertically; they must not split into rows.
    results = [
        (_box(10, 10, 120, 32), "Jean", 0.9),
        (_box(130, 12, 260, 34), "Dupont", 0.9),  # +2px wobble, same line
    ]
    assert _boxes_to_text(results) == "Jean Dupont"
