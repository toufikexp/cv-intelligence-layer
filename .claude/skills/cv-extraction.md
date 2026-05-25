# CV Extraction Skill

Covers the Document Processor + Entity Extractor + JSON-create paths.

## Document Processing Rules

- PDFs → PyMuPDF (`fitz`); DOCX → `python-docx` (DOCX tables are flattened to `cell | cell` rows)
- OCR trigger: any page yielding `< 50` characters of native text sets `needs_ocr=True`
- OCR is PDF-only — DOCX never goes through OCR
- OCR pipeline: per-page rasterize at `OCR_DPI` (default 150) → EasyOCR (fra+eng). GPU is used when `EASYOCR_GPU` is truthy (default `true` in `docker-compose.yml`); CPU otherwise. The reader is a process-wide singleton, pre-warmed at startup and in each Celery worker.
- Pages with sufficient native text are kept as-is; OCR runs only on the sparse ones
- OCR tasks are routed to the dedicated `ocr` queue via `task_routes` in
  `app/tasks/celery_app.py`. Run a worker with `-Q ocr` to handle them.
- `extraction_method` is one of `text_extraction`, `ocr_easyocr`, or `json_input`
  (the last is set by `POST /candidates`, never by the document pipeline)
- Always run language detection (`fasttext`, FR/EN/mixed) BEFORE LLM extraction
- Preserve `raw_text` on the CV row — used for re-indexing on PATCH and to
  ground the search document content
- Text cleaning utilities live in `app/utils/text_cleaning.py`

## PII redaction (CRITICAL — no PII reaches the LLM)

`EntityExtractor.extract` guarantees personal data never leaves the process to Gemini:

- **Local detection on the original text**: name/location/DOB via spaCy NER
  scoped to the contact block (`_extract_pii_entities`), email/phone/URLs via
  regex. A name-like-line fallback handles all-caps names spaCy tags as ORG.
- **Two-layer scrub before the LLM call**: `_strip_header_zone` replaces
  everything above the first section heading with `[CONTACT_DETAILS_REDACTED]`,
  then `_redact_pii` replaces any residual name/location/DOB/email/phone/URL with
  `[REDACTED_*]`. Only this redacted text (capped at 30k chars) is sent to Gemini.
- **Personal fields come from the local pass, not Gemini**: after the LLM call,
  `name`/`location`/`email`/`phone`/URLs on the returned profile are overwritten
  from the spaCy/regex results (`name` defaults to `"Unknown"`). The prompt also
  instructs Gemini to emit `null` for the redacted placeholders.
- **Readability gate**: `usable_char_count(text) < MIN_CV_TEXT_CHARS` (default
  200) → `422 UNPROCESSABLE_CV` in the extract endpoint, and a `failed` CV +
  `UnprocessableCVError` in the Celery `extract_entities` task.

## Entity Extraction Rules

- Two-pass: regex first (`email`, `phone`, URLs), then LLM for the structured
  fields. Regex values win when both are present.
- LLM prompt template: `prompts/cv_entity_extraction.md` — load via
  `prompt_loader`, never hardcode in Python.
- LLM provider: Google Gemini (default) or OpenAI-compatible HTTP via
  `LLM_PROVIDER` env var. Gemini uses `response_mime_type="application/json"`.
- Always pass the detected language as `detected_language` in the prompt context
- `_normalize_llm_output` in `app/services/entity_extractor.py` defensively
  coerces Gemini's common variations before Pydantic validation:
  - flatten `contact_info` nesting; coerce dict-shaped `name` to a string
  - flatten dict-of-lists `skills` → flat `list[str]`
  - rename `title|position`→`role`, `employer`→`company`,
    `field_of_study`→`field`, `school|university`→`institution`
  - normalize French language levels (`courant`→`fluent`, `débutant`→`beginner`, etc.)
  - flatten `certifications` (mix of strings and dicts) and `achievements`
    (mix of strings and dicts with `title|name|project|realization`)
  - guarantee `name` is non-empty (defaults to `"Unknown"`) so Pydantic passes
- Validate the normalized dict against `CandidateProfile` with
  `model_validate(data, strict=False)` so partial data still produces a row
- If the LLM returns invalid JSON: surface it as `LLMClientError`; the Celery
  task retries up to 3x.

## CandidateProfile fields

```python
name: str                              # required
email, phone, location, current_title, summary: str | None
linkedin_url, github_url, portfolio_url: AnyHttpUrl | None
skills: list[str]
experience: list[ExperienceEntry]
education: list[EducationEntry]
languages: list[LanguageEntry]         # level ∈ {native, fluent, advanced, intermediate, beginner}
certifications: list[str]
achievements: list[AchievementEntry]   # {title, year?, description?}
total_experience_years: float | None
```

`AchievementEntry` is intentionally distinct from `ExperienceEntry`: it captures
named deliverables ("Migration Data Lake vers AWS"), not job tenure.

## Phone normalization

Implemented in `app/services/entity_extractor.py:_normalize_phone()`:

```python
# Algerian: 05XX XXX XXX → +213 5XX XXX XXX
# French:   06 XX XX XX XX → +33 6 XX XX XX XX
# International: already has + prefix → keep as-is
```

Applied to both regex-extracted and LLM-returned phone numbers.

## File validation

```python
ALLOWED_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024  # default 20MB
```

`.doc` (legacy Word) and image files (JPG/PNG/TIFF) are rejected with `400
INVALID_FILE_TYPE`. Size violations return `400 FILE_TOO_LARGE`.

## JSON-create path (`POST /candidates`)

Skips the entire Celery pipeline (no file, no OCR, no LLM, no PII step — the
caller already supplies a structured `CandidateProfile`). The handler
(`create_cv_from_json` in `app/api/cv.py`):

1. `build_synthetic_text(profile)` from `app/services/indexing_bridge.py`
   composes a deterministic plain-text representation of the structured profile
   (Name, Title, Location, Email, Phone, Summary, Skills, Experience, Education,
   Languages, Certifications, Achievements).
2. `file_hash = sha256(synthetic_text)` — used for collection-level dedup.
3. `detect_language(synthetic_text)` — same fasttext call as the doc pipeline.
4. `cv_service.create_cv_for_indexing(...)` writes a row born `status="indexing"`
   with `extraction_method="json_input"` and a paired `CVProcessingJob`
   (`stage="indexing"`, `status="submitted"`, `progress_pct=90`).
5. Synchronous `ingest_documents(upsert=True)`; the returned Semantic Search
   `job_id` is stored as `search_ingest_job_id`. On failure the CV is marked
   `index_failed` and the handler returns `502 UPSTREAM_SEARCH_ERROR`.

The row is finalized to `ready` (or `index_failed`) by the **ingestion webhook**
exactly like the upload path — so if a `callback_url` was supplied, the Hiring
Platform DOES receive the completion callback once Semantic Search finishes
embedding. The handler returns `status="indexing"`, not `ready`.

## Exception handling

Service-level exceptions inherit from `app.exceptions.CVLayerError`:
- `FileValidationError` — invalid file type/size
- `EntityExtractionError` — extraction failures
- `LLMClientError` — LLM API failures
- `SearchClientError` — Semantic Search API failures
- `PipelineError` — pipeline stage failures
- `WebhookError` — webhook delivery or verification failures

API handlers translate these into `{"detail": ..., "code": ...}` with the
matching HTTP status.

## Pipeline flow (async, webhook-finalized)

The Celery chain in `app/tasks/ingestion.py:67` runs 7 tasks in order:

```
validate_file → extract_text → ocr_if_needed → detect_lang
              → extract_entities → store_profile → submit_to_search
```

`submit_to_search` POSTs to Semantic Search's async ingest endpoint, stores the
returned `search_ingest_job_id` on the CV row, and the chain ends there. The CV
is left in `status="indexing"`.

When Semantic Search finishes indexing, it fires `POST /api/webhooks/ingestion`
on the CV layer (HMAC-SHA256, secret `SEARCH_WEBHOOK_SECRET`). The
`IngestionWebhookService` correlates by `search_ingest_job_id`, sets the CV to
`ready` or `index_failed`, then enqueues `notify_hiring_platform` if the upload
included a `callback_url`. That task signs the body with `APP_WEBHOOK_SECRET`
and retries up to 5 times with exponential backoff (`2 ** (retries+1)` seconds)
on HTTP failure.

The HP callback payload contains only `{external_id, file_hash, status, error,
completed_at}` — no profile data. The HP must `GET /candidates/{cv_id}` (or
`GET /collections/{cid}/candidates/{external_id}`) to fetch the extracted
profile.
