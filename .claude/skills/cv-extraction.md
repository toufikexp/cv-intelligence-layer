# CV Extraction Skill

This skill covers the Document Processor + Entity Extractor components.

## Document Processing Rules

- Use PyMuPDF (`fitz`) for PDF text extraction, `python-docx` for DOCX
- OCR trigger: if any page yields < 50 characters of text
- OCR pipeline: rasterize at !`echo $OCR_DPI || echo 300` DPI → Surya OCR (primary) → EasyOCR (fallback if confidence < 0.6)
- Always detect language with fasttext BEFORE LLM extraction
- Preserve raw_text for reprocessing even after extraction

## Entity Extraction Rules

- Two-pass: regex first (email, phone, URLs), then LLM for structured data
- LLM prompt template is in `prompts/cv_entity_extraction.md` — load it, don't hardcode
- Always include detected language in the LLM prompt context
- Validate LLM output against CandidateProfile schema (`schemas/candidate_profile.json`)
- Use `model_validate(data, strict=False)` for LLM output — handle partial extraction gracefully
- If LLM returns invalid JSON: retry once with a shorter prompt, then store what regex found

## Phone normalization patterns

```python
# Algerian: 05XX XXX XXX → +213 5XX XXX XXX
# French: 06 XX XX XX XX → +33 6 XX XX XX XX
# International: already has + prefix → keep as-is
```

## File validation

```python
ALLOWED_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}
MAX_SIZE = 20 * 1024 * 1024  # 20MB
```
