# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is this

A Python FastAPI middleware between a **Hiring Platform** (external team) and the existing **Semantic Search as a Service** API (`toufikexp/Semantic-Search-as-service`). This layer handles CV-specific business logic; the search platform stays untouched.

```
Hiring Platform → CV Intelligence Layer (this) → Semantic Search API (existing, HTTP only)
```

## Tech stack

- Python 3.11+, FastAPI, uvicorn
- PostgreSQL 16 (JSONB profiles), SQLAlchemy 2.0 async + asyncpg
- Celery + Redis (async pipeline)
- PyMuPDF, python-docx, EasyOCR (fra+eng)
- Google Gemini API (default) or OpenAI-compatible local LLM for extraction/ranking/scoring
- Docker + Docker Compose

## Key commands

```bash
# Dev server
uvicorn app.main:app --reload --port 8001

# Run tests
pytest tests/ -v

# Single test
pytest tests/test_document_processor.py -v

# Celery worker
celery -A app.tasks.celery_app worker --loglevel=info

# OCR worker (dedicated queue)
celery -A app.tasks.celery_app worker --loglevel=info -Q ocr

# DB migration
alembic upgrade head

# New migration
alembic revision --autogenerate -m "description"

# Type check
mypy app/ --ignore-missing-imports

# Lint
ruff check app/ tests/
```

## Architecture rules (CRITICAL)

1. **Never import from or modify the Semantic Search codebase.** All interaction via HTTP through `app/services/search_client.py`
2. **All HTTP calls to external services go through dedicated client classes** in `app/services/` — never raw httpx in routes or tasks
3. **All LLM prompts live in `prompts/*.md`** — loaded at startup, never hardcoded in Python
4. **Celery tasks must be idempotent** — check state before acting, safe to retry
5. **Pydantic v2 validates all external input AND all LLM output**
6. **Every DB change requires an Alembic migration**
7. **The Hiring Platform never calls Semantic Search directly** — CV layer proxies everything
8. **Service-level exceptions inherit from `app.exceptions.CVLayerError`**

## Code style

- Type hints on every function signature
- `async def` for all I/O functions
- Google-style docstrings on public functions
- Imports: stdlib → third-party → local, separated by blank lines
- Structured JSON logging with `cv_id` and `job_id` correlation IDs
- Error format: `{"detail": "msg", "code": "ERROR_CODE"}`

## Key data model patterns

**Two correlation keys on `CVProfile`** — understand the distinction before touching upload/search/rank code:
- `external_id` — caller-supplied business key (e.g. `EMP-001`). NOT NULL, unique per `(collection_id, external_id)`. This is the authoritative join key echoed on search/rank results. The Hiring Platform uses this to correlate CV layer records with its own DB.
- `file_hash` — SHA-256 of the file bytes. Used only for deduplication (`DUPLICATE_FILE` 409). Never use as a document id.
- `search_doc_external_id` — legacy column; equals `external_id` for all rows created after migration `0003`. Kept for backward-compatibility with pre-migration rows.

**Semantic Search document id** = `cv.external_id`. The `submit_to_search` task raises `RuntimeError` if `external_id` is None; never fall back to `file_hash`.

**Indexing content** = raw CV text (`payload["raw_text"]`), not a formatted profile projection. `build_search_document` in `app/services/indexing_bridge.py` receives `raw_text` explicitly.

**Two-phase ranking** (`app/services/ranking_engine.py`):
1. Recall — semantic search via Search API (`hybrid` mode, `rerank=True`) to get top-N candidates.
2. Scoring — parallel LLM calls (Gemini, concurrency controlled by `ranking_llm_concurrency` setting) produce per-component scores. Composite = weighted sum of `semantic` (0.30) + `skills` (0.25) + `experience` (0.25) + `education` (0.10) + `language` (0.10). Weights are overridable per-request via `RankingRequest.weights`.

## Project structure

```
app/
  main.py              # FastAPI app factory
  config.py            # pydantic-settings, env-based
  exceptions.py        # CVLayerError base + subclasses
  api/                 # Thin route handlers → delegate to services
    router.py          # Router registration
    cv.py, ranking.py, scoring.py, collections.py, health.py
    webhooks.py        # Semantic Search ingestion webhook receiver
    auth.py            # Bearer token validation
  models/
    database.py        # SQLAlchemy engine, session, ORM models (Base, CVProfile, etc.)
    schemas.py         # Pydantic request/response schemas
  services/
    document_processor.py   # PDF/DOCX text extraction
    ocr_service.py          # EasyOCR pipeline (fra+eng)
    entity_extractor.py     # Regex + LLM extraction + phone normalization
    indexing_bridge.py      # CandidateProfile + raw_text → Search API document
    ranking_engine.py       # Semantic recall + LLM ranking
    answer_scorer.py        # Similarity + LLM grading
    search_client.py        # HTTP client for Semantic Search API
    llm_client.py           # Gemini / OpenAI-compatible wrapper
    cv_service.py           # CV CRUD + get_cv_by_external_id
    cv_search.py            # CV search via Semantic Search
    prompt_loader.py        # Prompt template loading
    ingestion_webhook_service.py  # Handles Semantic Search ingestion webhooks
  tasks/
    celery_app.py           # Celery config (OCR routed to 'ocr' queue)
    ingestion.py            # 7-stage pipeline + HP callback task
  utils/
    language_detect.py, text_cleaning.py, file_validation.py, logging.py,
    webhook_signing.py      # HMAC-SHA256 signing/verification
tests/
  conftest.py               # Shared fixtures and factories
```

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/v1/candidates/upload | Upload CV (PDF/DOCX), triggers async pipeline. `external_id` required. |
| GET | /api/v1/candidates/{cv_id} | Get structured candidate profile by internal UUID |
| GET | /api/v1/candidates/{cv_id}/status | Check processing status by internal UUID |
| PUT | /api/v1/candidates/{cv_id} | Replace CV file, re-run pipeline (preserves `cv_id`/`external_id`) |
| PATCH | /api/v1/candidates/{cv_id} | Partially update structured profile; re-indexes synchronously |
| DELETE | /api/v1/candidates/{cv_id} | Remove CV and search index by internal UUID |
| GET | /api/v1/collections/{collection_id}/candidates/{external_id} | Get profile by caller-supplied business key |
| GET | /api/v1/collections/{collection_id}/candidates/{external_id}/status | Get status by business key |
| PUT | /api/v1/collections/{collection_id}/candidates/{external_id} | Replace CV file by business key |
| PATCH | /api/v1/collections/{collection_id}/candidates/{external_id} | Partially update profile by business key |
| DELETE | /api/v1/collections/{collection_id}/candidates/{external_id} | Delete by business key |
| POST | /api/v1/candidates/search | Search CVs with filters/facets |
| POST | /api/v1/candidates/rank | Rank candidates against JD (synchronous) |
| POST | /api/v1/candidates/score-answers | Score test answers |
| POST | /api/v1/collections | Create collection |
| GET | /api/v1/collections | List collections |
| POST | /api/webhooks/ingestion | Semantic Search ingestion webhook |
| GET | /health | Liveness probe |
| GET | /ready | Readiness probe |

## Docker / local dev notes

`./app` and `./prompts` are bind-mounted into the containers — code changes take effect on restart, no rebuild needed. `./alembic` is **not** mounted, so new migration files require a full rebuild (`docker compose up -d --build cv-api cv-worker`).

Accepted upload MIME types: `application/pdf` and `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (`.docx` only — legacy `.doc` returns `400 INVALID_FILE_TYPE`).

## Key references (read on demand, don't memorize)

- Full spec: `SPEC.md`
- LLM prompts: `prompts/cv_entity_extraction.md`, `prompts/cv_ranking.md`, `prompts/answer_scoring.md`
- Data model: `schemas/candidate_profile.json`
- API contract: `schemas/openapi_cv_layer.yaml`

## Bilingual (FR/EN)

- Language detected via fasttext, stored in `cv_profiles.language`
- LLM prompts include detected language as context
- OCR uses `fra+eng` language config
- Never assume a CV is in English

## Environment variables

See `.env.example` for the full list. Key ones: `DATABASE_URL`, `REDIS_URL`, `SEARCH_API_BASE_URL`, `SEARCH_API_KEY`, `LLM_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL`, `SEARCH_WEBHOOK_SECRET`, `APP_WEBHOOK_SECRET`.
