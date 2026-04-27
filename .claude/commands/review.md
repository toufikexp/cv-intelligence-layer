Review the recent changes as a senior engineer. Be critical.

Check for:

1. **Architecture violations**:
   - Anything calling Semantic Search outside `app/services/search_client.py`?
   - Hardcoded LLM prompts (must live in `prompts/*.md`, loaded via
     `prompt_loader`)?
   - Raw SQL or schema mutation outside Alembic?
   - HP code calling Semantic Search directly (the CV layer must proxy
     everything)?

2. **Type safety**:
   - All public functions have type hints?
   - Pydantic v2 validates external input AND LLM output?
   - PATCH-style models use `extra="forbid"` so unknown fields fail loudly?

3. **Error handling**:
   - Errors return `{"detail": ..., "code": ...}` with the right HTTP status?
   - Service-level exceptions inherit from `app.exceptions.CVLayerError`?
   - Celery tasks log + re-raise (don't swallow)?
   - Sync re-index paths mark the CV `index_failed` before returning 502?

4. **Idempotency**:
   - Each Celery task safe to retry? (state guards on `cv.status`)
   - Webhook handlers short-circuit on already-finalized CVs?
   - Re-upload (`PUT`) wipes derived fields without losing identity columns
     (`cv_id`, `external_id`, `collection_id`, `created_at`)?
   - JSON-create uses `upsert=True` on Search ingest?

5. **Bilingual (FR/EN)**:
   - Language detected before LLM extraction (fasttext)?
   - LLM prompt includes `detected_language` as context?
   - OCR uses `["fr", "en"]`?

6. **Security**:
   - File validation (MIME allowlist, size cap from `MAX_FILE_SIZE_MB`)?
   - No PII in logs (redact email/phone/file content)?
   - `Depends(get_api_key)` on every authenticated route?
   - HMAC-SHA256 verification on `/api/webhooks/ingestion`
     (`SEARCH_WEBHOOK_SECRET`)?
   - HMAC-SHA256 signing on outbound HP callbacks (`APP_WEBHOOK_SECRET`)?

7. **Webhooks**:
   - `IngestionWebhookService.handle` is idempotent on `status ∈ {ready, index_failed}`?
   - HP callback retries with exponential backoff, max 5 attempts?
   - Signature verification raises 401 (not 500) on mismatch?

8. **Data model invariants**:
   - `external_id` is the Semantic Search document id — never `file_hash`
   - `submit_to_search` raises if `external_id` is None
   - Indexing content is `raw_text` (or `build_synthetic_text(profile)` for
     JSON-create) — not a formatted projection
   - Unique constraints respected before commit
     (`uq_cv_profiles_collection_file_hash`,
     `uq_cv_profiles_collection_external_id`,
     `uq_cv_profiles_collection_email`)

9. **Tests**:
   - External services (`SemanticSearchClient`, `LLMClient`) mocked?
   - 4xx error paths covered (404, 409, 422, 502)?
   - Edge cases: empty `raw_text`, missing `external_id`, status race?

Run the checks:
```bash
mypy app/ --ignore-missing-imports
ruff check app/ tests/
pytest tests/ -v
```

Report issues ranked by severity.
