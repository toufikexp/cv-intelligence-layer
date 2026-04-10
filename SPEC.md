# CV Intelligence Layer — Full Specification

## 1. Ingestion Pipeline

The CV processing pipeline is fully asynchronous via Celery task chain. Each stage is a separate task, idempotent and retriable.

### Pipeline stages

| # | Stage | Action | Output | Failure Mode |
|---|-------|--------|--------|--------------|
| 1 | File Validation | Validate MIME (PDF/DOCX), size (<20MB), compute SHA-256 hash | Validated file path + hash | Reject with 400 |
| 2 | Text Extraction | PyMuPDF for PDF, python-docx for DOCX. If text < 50 chars/page → route to OCR | Raw text + method | Retry with OCR fallback |
| 3 | OCR (conditional) | Rasterize at 300 DPI, run EasyOCR (fra+eng). Routed to dedicated `ocr` queue | OCR text | Mark as partial_ocr |
| 4 | Language Detection | fasttext lid.176.bin on extracted text | Language code (fr/en/mixed) | Default to 'mixed' |
| 5 | Entity Extraction | Regex pass (email, phone, URLs) + LLM structured extraction + phone normalization | CandidateProfile JSON | Retry LLM 2x, then store partial |
| 6 | Profile Storage | Upsert CandidateProfile into PostgreSQL | cv_id | DB retry 3x |
| 7 | Search Indexing | Build search document, POST to Semantic Search /documents (async ingest). Save `search_ingest_job_id` for webhook correlation. Pipeline chain ends here. | search_doc_external_id + ingest job_id | Queue for retry |
| 8 | Webhook Finalize | Semantic Search fires `POST /api/webhooks/ingestion` when indexing completes. CV Layer verifies HMAC, updates status to `ready` or `index_failed`, then fires callback to Hiring Platform if `callback_url` was provided. | Final status | Idempotent; ignored for already-finalized CVs |

### OCR detection logic

```python
def needs_ocr(page_text: str) -> bool:
    return len(page_text.strip()) < 50
```

Process page-by-page: some pages may be text-based while others are scanned.

### Phone normalization

```python
# Algerian: 05XX XXX XXX → +213 5XX XXX XXX
# French: 06 XX XX XX XX → +33 6 XX XX XX XX
# International: already has + prefix → keep as-is
```

### Search document construction

The indexing bridge builds content for embedding:
```
{current_title} | {name}
Skills: {skills_comma_separated}
Experience: {role1 at company1}, {role2 at company2}, ...
Education: {degree from institution}
{summary}
```

Metadata mapping for faceted search:
```json
{
  "skills": ["Python", "SQL"],
  "experience_years": 5,
  "language": "fr",
  "location": "Algiers",
  "education_level": "master"
}
```

### Webhook flow (async ingestion + callbacks)

The pipeline uses a dual-webhook pattern for async coordination:

```
Hiring Platform              CV Layer                        Semantic Search
     │── POST /upload ─────────▶│                                  │
     │◀── 202 {cv_id, job_id}  │                                  │
     │                          │ stages 1-6: extract → store      │
     │                          │ stage 7: submit_to_search ──────▶│
     │                          │◀── 202 {ingest_job_id}          │
     │                          │                                  │── indexing...
     │                          │◀── POST /api/webhooks/ingestion │
     │                          │── 200 {received: true} ─────────▶│
     │◀── POST callback_url ───│                                  │
```

**Incoming webhook** (Semantic Search → CV Layer):
- Endpoint: `POST /api/webhooks/ingestion`
- HMAC-SHA256 signature in `X-Webhook-Signature` header (secret: `SEARCH_WEBHOOK_SECRET`)
- Payload: `{event, job_id, collection_id, status, total_docs, processed_docs, failed_docs, documents[], completed_at}`
- `status`: `"completed"` or `"completed_with_errors"`
- Correlation: CV Layer looks up `search_ingest_job_id` in `cv_profiles` to find the CV

**Outgoing callback** (CV Layer → Hiring Platform):
- Fires to `callback_url` provided during upload (if set)
- HMAC-SHA256 signature in `X-Webhook-Signature` header (secret: `HP_WEBHOOK_SECRET`)
- Payload: `{external_id, file_hash, status, error, completed_at}`
- `status`: `"ready"` or `"index_failed"`
- Retries: 5 attempts with exponential backoff via Celery task

## 2. API Contract

See `schemas/openapi_cv_layer.yaml` for the complete OpenAPI spec.

### Endpoints summary

| Method | Endpoint | Description | Async |
|--------|----------|-------------|-------|
| POST | /api/v1/candidates/upload | Upload CV file, triggers pipeline | Yes - returns job_id |
| GET | /api/v1/candidates/{cv_id} | Get structured candidate profile | No |
| GET | /api/v1/candidates/{cv_id}/status | Check processing status | No |
| DELETE | /api/v1/candidates/{cv_id} | Remove CV and search index | No |
| POST | /api/v1/candidates/search | Search CVs with filters/facets | No |
| POST | /api/v1/candidates/rank | Rank candidates against JD | Yes for large sets |
| POST | /api/v1/candidates/score-answers | Score test answers vs references | No |
| POST | /api/v1/collections | Create CV collection | No |
| GET | /api/v1/collections | List CV collections | No |
| POST | /api/webhooks/ingestion | Receive Semantic Search ingest webhook | Webhook receiver |

### Authentication

Same pattern as Semantic Search API: `Authorization: Bearer <api_key>` header.

## 3. Database Schema

### Primary table: cv_profiles

| Field | Type | Indexed | Notes |
|-------|------|---------|-------|
| cv_id | UUID (PK) | Yes | uuid7 (time-ordered) |
| external_id | VARCHAR(255) | Yes (unique) | ID from hiring platform |
| collection_id | UUID (FK) | Yes | Maps to Semantic Search collection |
| candidate_name | VARCHAR(255) | Yes (trigram) | For fast name lookup |
| email | VARCHAR(255) | Yes (unique/collection) | Deduplication key |
| phone | VARCHAR(50) | Yes | International format |
| profile_data | JSONB | GIN index | Full CandidateProfile |
| raw_text | TEXT | No | Preserved for reprocessing |
| language | VARCHAR(5) | Yes | fr, en, mixed |
| extraction_method | VARCHAR(20) | No | text_extraction, ocr_easyocr |
| search_doc_external_id | VARCHAR(255) | Yes | Reference to search platform doc |
| search_ingest_job_id | VARCHAR(64) | Yes | Semantic Search ingest job_id for webhook correlation |
| file_hash | VARCHAR(64) | Yes (unique/collection) | SHA-256 for dedup |
| status | VARCHAR(20) | Yes | pending/extracting/indexing/ready/failed/index_failed |
| callback_url | VARCHAR(2048) | No | Hiring Platform webhook URL for completion notification |
| created_at | TIMESTAMPTZ | Yes | Upload timestamp |
| updated_at | TIMESTAMPTZ | No | Last modification |

### Supporting tables

- **cv_jobs**: Job descriptions for ranking (job_id, collection_id, description, required_skills, created_at)
- **cv_ranking_results**: Cached ranking results (job_id, cv_id, composite_score, llm_reasoning, ranked_at)
- **cv_answer_sessions**: Test scoring sessions (session_id, cv_id, scores, total_score)
- **cv_processing_jobs**: Async job tracking (job_id, cv_id, stage, status, error_message, timestamps)

## 4. Ranking Engine

### Two-phase ranking

**Phase 1 — Semantic Recall:**
- Send job description to Semantic Search `/search` with `mode: "hybrid"`, `rerank: true`
- Retrieve top-N candidates (configurable, default 30)
- Fast: < 500ms

**Phase 2 — LLM Evaluation:**
- For each candidate, send JD + structured profile to LLM (Gemini default)
- Multi-criteria scoring: skills (0.25), experience (0.25), education (0.10), language (0.10)
- Parallelized with `asyncio.Semaphore` (default concurrency: 5)
- Prompt template: `prompts/cv_ranking.md`

**Composite score:**
```python
composite = (
    weights["semantic"] * search_score +      # 0.30
    weights["skills"] * llm.skills_score +     # 0.25
    weights["experience"] * llm.exp_score +    # 0.25
    weights["education"] * llm.edu_score +     # 0.10
    weights["language"] * llm.lang_score       # 0.10
)
```

## 5. Answer Scorer

### Hybrid scoring strategy

```
if embedding_score >= 0.7:
    → Accept with embedding score (fast, no LLM cost)
elif embedding_score >= 0.3:
    → Escalate to LLM grading (detailed feedback)
else:
    → Flag as insufficient (no LLM cost)
```

Reference answers are ingested into a dedicated Semantic Search collection per test.

## 6. Semantic Search API Integration

All calls go through `app/services/search_client.py`:

```python
class SemanticSearchClient:
    async def create_collection(payload) -> dict
    async def list_collections(limit, offset) -> dict
    async def ingest_documents(collection_id, documents, upsert=True) -> dict
    async def search(collection_id, query, filters, limit, facets, mode, rerank) -> dict
    async def suggest(collection_id, prefix, limit) -> dict
    async def get_document(collection_id, external_id) -> dict
    async def delete_document(collection_id, external_id) -> None
    async def delete_document_if_exists(collection_id, external_id) -> None
```

Uses `httpx.AsyncClient` with connection pooling. Circuit breaker via `tenacity`: retry 3x with exponential backoff (1s, 2s, 4s).

## 7. Performance Targets

| Operation | Target |
|-----------|--------|
| CV Upload → Ready (text PDF) | < 30 seconds |
| CV Upload → Ready (scanned PDF) | < 60 seconds |
| Search latency | < 500ms |
| Ranking (30 candidates) | < 15 seconds |
| Answer scoring (single, embedding) | < 3 seconds |
| Answer scoring (single, LLM) | < 8 seconds |

## 8. Environment Variables

```bash
APP_ENV=development
APP_PORT=8001
APP_API_KEY=dev_key_change_me
DATABASE_URL=postgresql+asyncpg://cv_user:password@cv-db:5432/cv_intelligence
REDIS_URL=redis://cv-redis:6379/0
CELERY_BROKER_URL=redis://cv-redis:6379/0
SEARCH_API_BASE_URL=http://semantic-search-api:8000
SEARCH_API_KEY=your_key
SEARCH_INGEST_API_KEY=your_ingest_key
LLM_PROVIDER=gemini
LLM_API_KEY=your_key
LLM_MODEL=gemini-2.5-flash
LLM_BASE_URL=                    # only for openai_compatible provider
UPLOAD_DIR=/data/uploads
MAX_FILE_SIZE_MB=20
OCR_DPI=300
OCR_CONFIDENCE_THRESHOLD=0.6
RANKING_DEFAULT_RECALL_SIZE=30
RANKING_LLM_CONCURRENCY=5
```
