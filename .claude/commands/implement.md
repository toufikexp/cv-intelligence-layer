Implement the following component or feature for the CV Intelligence Layer:

$ARGUMENTS

Before writing any code:
1. Read `SPEC.md` for full specifications
2. Read the relevant prompt file in `prompts/` if this involves LLM integration
3. Read `schemas/candidate_profile.json` if this touches the data model
4. Read `schemas/openapi_cv_layer.yaml` if this involves an API endpoint

Implementation steps:
1. Create/update Pydantic schemas in `app/models/schemas.py`
   - Use `model_config = {"extra": "forbid"}` on PATCH-style partial models
     so unknown fields fail loudly as 422 instead of being silently dropped
   - Re-validate merged dicts through the strict `CandidateProfile` model so
     bad patches surface at the API boundary, not at write time
2. Implement business logic in the appropriate `app/services/*.py` file
   - Service methods raise `HTTPException` for caller-visible failures
     (`{"detail": ..., "code": ...}`) — never bare exceptions
   - All HTTP egress to Semantic Search goes through `search_client.py`
3. Wire up the API route in `app/api/*.py` (thin handler, delegate to service)
   - Apply `Depends(get_api_key)` on every authenticated route
   - For dual addressing (`cv_id` and `(collection_id, external_id)`), factor
     the shared logic into a helper and call it from both handlers — see
     `_replace_cv_file` and `_apply_profile_patch` in `app/api/cv.py`
4. If async pipeline stage: add Celery task in `app/tasks/ingestion.py`
   - Tasks must be idempotent (check status before mutating)
   - Use `_make_session()` for a fresh engine per task; never share the
     module-level engine across forked workers
5. DB schema change → Alembic migration:
   `alembic revision --autogenerate -m "description"`
   - Remember `./alembic` is NOT bind-mounted, so Docker requires
     `docker compose up -d --build cv-api cv-worker` after a new revision
6. Write tests in `tests/`
   - Mock external services (`SemanticSearchClient`, `LLMClient`) — no real
     network calls in tests
   - Cover the happy path, the 4xx error paths, and the 502 upstream-failure
     path when the change touches Search
7. Run `mypy app/ --ignore-missing-imports` and `ruff check app/ tests/`
8. Run `pytest tests/ -v` and confirm everything passes
