"""Tests for document text extraction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.document_processor import DocumentProcessor, _needs_ocr


class TestNeedsOcr:
    def test_short_text_needs_ocr(self) -> None:
        assert _needs_ocr("Hi") is True

    def test_empty_text_needs_ocr(self) -> None:
        assert _needs_ocr("") is True

    def test_long_text_no_ocr(self) -> None:
        assert _needs_ocr("A" * 100) is False

    def test_exactly_50_chars_no_ocr(self) -> None:
        assert _needs_ocr("A" * 50) is False

    def test_49_chars_needs_ocr(self) -> None:
        assert _needs_ocr("A" * 49) is True


@pytest.mark.asyncio
async def test_extract_pdf() -> None:
    mock_page = MagicMock()
    mock_page.get_text.return_value = "This is a PDF page with enough text to skip OCR detection and be useful for extraction."

    mock_doc = MagicMock()
    mock_doc.__iter__ = lambda self: iter([mock_page])
    mock_doc.close = MagicMock()

    with patch("app.services.document_processor.fitz.open", return_value=mock_doc):
        processor = DocumentProcessor()
        result = await processor.extract(Path("/fake/cv.pdf"), "application/pdf")

    assert "PDF page" in result.text
    assert result.method == "text_extraction"
    assert result.needs_ocr is False


@pytest.mark.asyncio
async def test_extract_pdf_detects_ocr_needed() -> None:
    mock_page = MagicMock()
    mock_page.get_text.return_value = "Hi"

    mock_doc = MagicMock()
    mock_doc.__iter__ = lambda self: iter([mock_page])
    mock_doc.close = MagicMock()

    with patch("app.services.document_processor.fitz.open", return_value=mock_doc):
        processor = DocumentProcessor()
        result = await processor.extract(Path("/fake/cv.pdf"), "application/pdf")

    assert result.needs_ocr is True


@pytest.mark.asyncio
async def test_extract_docx() -> None:
    mock_para = MagicMock()
    mock_para.text = "This is a DOCX paragraph."

    mock_doc = MagicMock()
    mock_doc.paragraphs = [mock_para]
    mock_doc.tables = []

    with patch("app.services.document_processor.Document", return_value=mock_doc):
        processor = DocumentProcessor()
        result = await processor.extract(Path("/fake/cv.docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    assert "DOCX paragraph" in result.text
    assert result.method == "text_extraction"
    assert result.needs_ocr is False
