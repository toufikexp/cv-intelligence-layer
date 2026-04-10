Review the recent changes as a senior engineer. Be critical.

Check for:
1. **Architecture violations**: Does anything call the Semantic Search API directly (outside `search_client.py`)? Any hardcoded LLM prompts? Any raw SQL instead of Alembic?
2. **Type safety**: All functions have type hints? Pydantic validates all external input and LLM output?
3. **Error handling**: Proper error responses with `{"detail": ..., "code": ...}` format? Celery tasks catch and log before re-raising?
4. **Idempotency**: Can each Celery task be safely retried?
5. **Bilingual**: Does the code handle French and English CVs? Language detection before LLM calls?
6. **Security**: File validation (MIME, size)? No PII in logs? API key auth on all endpoints? HMAC-SHA256 verification on webhook endpoints?
7. **Webhooks**: Are webhook handlers idempotent? Is signature verification applied? Are HP callbacks retried on failure?
8. **Tests**: Are external services mocked? Edge cases covered?

Run the checks:
```bash
mypy app/ --ignore-missing-imports
ruff check app/ tests/
pytest tests/ -v
```

Report issues ranked by severity.
