# CV Extraction Skill

This skill covers the Document Processor + Entity Extractor components.

## Document Processing Rules

- Use PyMuPDF (`fitz`) for PDF text extraction, `python-docx` for DOCX
- OCR trigger: if any page yields < 50 characters of text
- OCR pipeline: rasterize at 300 DPI → EasyOCR (fra+eng)
- OCR tasks are routed to the dedicated `ocr` queue via Celery task_routes
- Always detect language with fasttext BEFORE LLM extraction
- Preserve raw_text for reprocessing even after extraction
- Text cleaning utilities available in `app/utils/text_cleaning.py`

## Entity Extraction Rules

- Two-pass: regex first (email, phone, URLs), then LLM for structured data
- LLM prompt template is in `prompts/cv_entity_extraction.md` — load it, don't hardcode
- LLM provider: Google Gemini (default) or OpenAI-compatible via `LLM_PROVIDER` env var
- Always include detected language in the LLM prompt context
- Validate LLM output against CandidateProfile schema (`schemas/candidate_profile.json`)
- Use `model_validate(data, strict=False)` for LLM output — handle partial extraction gracefully
- If LLM returns invalid JSON: retry once with a shorter prompt, then store what regex found

## Phone normalization patterns

Implemented in `app/services/entity_extractor.py:_normalize_phone()`:

```python
# Algerian: 05XX XXX XXX → +213 5XX XXX XXX
# French: 06 XX XX XX XX → +33 6 XX XX XX XX
# International: already has + prefix → keep as-is
```

Applied to both regex-extracted and LLM-returned phone numbers.

## File validation

```python
ALLOWED_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}
MAX_SIZE = 20 * 1024 * 1024  # 20MB
```

## Exception handling

Service-level exceptions inherit from `app.exceptions.CVLayerError`:
- `FileValidationError` — invalid file type/size
- `EntityExtractionError` — extraction failures
- `LLMClientError` — LLM API failures
- `PipelineError` — pipeline stage failures
