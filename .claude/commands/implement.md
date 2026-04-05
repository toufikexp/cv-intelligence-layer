Implement the following component or feature for the CV Intelligence Layer:

$ARGUMENTS

Before writing any code:
1. Read `SPEC.md` for full specifications
2. Read the relevant prompt file in `prompts/` if this involves LLM integration
3. Read `schemas/candidate_profile.json` if this touches the data model
4. Read `schemas/openapi_cv_layer.yaml` if this involves an API endpoint

Implementation steps:
1. Create/update Pydantic schemas in `app/models/schemas.py`
2. Implement business logic in the appropriate `app/services/*.py` file
3. Wire up the API route in `app/api/*.py` (thin handler, delegate to service)
4. If async pipeline stage: add Celery task in `app/tasks/ingestion.py`
5. Create Alembic migration if DB schema changed: `alembic revision --autogenerate -m "description"`
6. Write tests in `tests/` — mock external services (Search API, LLM API)
7. Run `mypy app/ --ignore-missing-imports` and `ruff check app/` to verify
8. Run `pytest tests/ -v` to confirm tests pass
