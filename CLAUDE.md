# CV Intelligence Layer

## What is this

A Python FastAPI middleware between a **Hiring Platform** (external team) and the existing **Semantic Search as a Service** API (`toufikexp/Semantic-Search-as-service`). This layer handles CV-specific business logic; the search platform stays untouched.

```
Hiring Platform → CV Intelligence Layer (this) → Semantic Search API (existing, HTTP only)
```

## Tech stack

- Python 3.11+, FastAPI, uvicorn
- PostgreSQL 16 (JSONB profiles), SQLAlchemy 2.0 async + asyncpg
- Celery + Redis (async pipeline)
- PyMuPDF, python-docx, Surya OCR, EasyOCR
- Anthropic Claude API (Sonnet) for extraction/ranking/scoring
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

# GPU OCR worker
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

## Code style

- Type hints on every function signature
- `async def` for all I/O functions
- Google-style docstrings on public functions
- Imports: stdlib → third-party → local, separated by blank lines
- Structured JSON logging with `cv_id` and `job_id` correlation IDs
- Error format: `{"detail": "msg", "code": "ERROR_CODE"}`

## Project structure

```
app/
  main.py              # FastAPI app factory
  config.py            # pydantic-settings, env-based
  api/                 # Thin route handlers → delegate to services
    cv.py, ranking.py, scoring.py, collections.py
  models/
    database.py        # SQLAlchemy models
    schemas.py         # Pydantic request/response schemas
  services/
    document_processor.py   # PDF/DOCX text extraction
    ocr_service.py          # Surya + EasyOCR pipeline
    entity_extractor.py     # Regex + LLM extraction
    indexing_bridge.py      # CandidateProfile → Search API
    ranking_engine.py       # Semantic recall + LLM ranking
    answer_scorer.py        # Similarity + LLM grading
    search_client.py        # HTTP client for Semantic Search API
    llm_client.py           # Anthropic API wrapper
  tasks/
    celery_app.py           # Celery config
    ingestion.py            # Pipeline task chain
  utils/
    language_detect.py, text_cleaning.py, file_validation.py
```

## Key references (read on demand, don't memorize)

- Full spec: `@SPEC.md`
- LLM prompts: `@prompts/cv_entity_extraction.md`, `@prompts/cv_ranking.md`, `@prompts/answer_scoring.md`
- Data model: `@schemas/candidate_profile.json`
- API contract: `@schemas/openapi_cv_layer.yaml`
- Architecture doc: `@docs/solution_architecture.md`

## Bilingual (FR/EN)

- Language detected via fasttext, stored in `cv_profiles.language`
- LLM prompts include detected language as context
- OCR uses `fra+eng` language config
- Never assume a CV is in English

## Environment variables

See `.env.example` for the full list. Key ones: `DATABASE_URL`, `REDIS_URL`, `SEARCH_API_BASE_URL`, `SEARCH_API_KEY`, `ANTHROPIC_API_KEY`.
