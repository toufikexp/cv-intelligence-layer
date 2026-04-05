# CV Intelligence Layer — Full Specification

## 1. Ingestion Pipeline

The CV processing pipeline is fully asynchronous via Celery task chain. Each stage is a separate task, idempotent and retriable.

### Pipeline stages

| # | Stage | Action | Output | Failure Mode |
|---|-------|--------|--------|--------------|
| 1 | File Validation | Validate MIME (PDF/DOCX), size (<20MB), compute SHA-256 hash | Validated file path + hash | Reject with 400 |
| 2 | Text Extraction | PyMuPDF for PDF, python-docx for DOCX. If text < 50 chars/page → route to OCR | Raw text + method | Retry with OCR fallback |
| 3 | OCR (conditional) | Rasterize at 300 DPI, run Surya OCR (fra+eng). Fallback: EasyOCR | OCR text | Mark as partial_ocr |
| 4 | Language Detection | fasttext lid.176.bin on extracted text | Language code (fr/en/mixed) | Default to 'mixed' |
| 5 | Entity Extraction | Regex pass (email, phone, URLs) + LLM structured extraction (Claude Sonnet) | CandidateProfile JSON | Retry LLM 2x, then store partial |
| 6 | Profile Storage | Upsert CandidateProfile into PostgreSQL | cv_id | DB retry 3x |
| 7 | Search Indexing | Build search document, POST to Semantic Search /documents with upsert:true | search_doc_external_id | Queue for retry |
| 8 | Status Update | Set status=ready, fire webhook if configured | Final status | Log and alert |

### OCR detection logic

```python
def needs_ocr(page_text: str) -> bool:
    return len(page_text.strip()) < 50
```

Process page-by-page: some pages may be text-based while others are scanned.

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
| extraction_method | VARCHAR(20) | No | text_extraction, ocr_surya, ocr_easyocr |
| search_doc_external_id | VARCHAR(255) | Yes | Reference to search platform doc |
| file_hash | VARCHAR(64) | Yes (unique/collection) | SHA-256 for dedup |
| status | VARCHAR(20) | Yes | pending/extracting/indexing/ready/failed |
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
- For each candidate, send JD + structured profile to Claude Sonnet
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
    async def create_collection(name, description, metadata_schema) -> CollectionResponse
    async def ingest_documents(collection_id, documents, upsert=True) -> IngestResponse
    async def search(collection_id, query, filters, limit, facets) -> SearchResponse
    async def suggest(collection_id, prefix, limit) -> SuggestResponse
    async def get_document(collection_id, external_id) -> DocumentResponse
    async def delete_document(collection_id, external_id) -> None
    async def get_job_status(job_id) -> JobStatusResponse
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
DATABASE_URL=postgresql+asyncpg://cv_user:password@cv-db:5432/cv_intelligence
REDIS_URL=redis://cv-redis:6379/0
CELERY_BROKER_URL=redis://cv-redis:6379/0
SEARCH_API_BASE_URL=http://semantic-search-api:8000
SEARCH_API_KEY=your_key
ANTHROPIC_API_KEY=your_key
ANTHROPIC_MODEL=claude-sonnet-4-20250514
UPLOAD_DIR=/data/uploads
MAX_FILE_SIZE_MB=20
OCR_DPI=300
OCR_CONFIDENCE_THRESHOLD=0.6
RANKING_DEFAULT_RECALL_SIZE=30
RANKING_LLM_CONCURRENCY=5
```
