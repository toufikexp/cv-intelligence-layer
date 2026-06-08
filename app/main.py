from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.utils.logging import configure_logging


class UTF8JSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm ML models so the first request doesn't pay cold-start."""
    log = logging.getLogger("cv_layer.startup")

    # spaCy NER models (used for PII redaction before LLM calls)
    try:
        from app.services.entity_extractor import load_spacy_models

        log.info("Loading spaCy NER models…")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, load_spacy_models)
        log.info("spaCy NER models ready.")
    except Exception as exc:
        log.warning("spaCy model load failed (PII redaction will be unavailable): %s", exc)

    # EasyOCR model
    try:
        from app.services.ocr_service import _get_reader

        log.info("Pre-warming EasyOCR model…")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _get_reader)
        log.info("EasyOCR model ready.")
    except Exception as exc:  # never block startup on a pre-warm failure
        log.warning("OCR pre-warm failed (will load on first request): %s", exc)

    # SkillConnect catalogs — load from DB + (fail-soft) refresh from API, then
    # start a periodic refresh. Never block/crash startup on a catalog failure.
    catalog_task: asyncio.Task[None] | None = None
    try:
        from app.config import get_settings
        from app.services.catalog_refresh import periodic_refresh_loop, refresh_catalog

        settings = get_settings()
        await refresh_catalog(fetch_api=True)
        if settings.skillconnect_api_base_url:
            catalog_task = asyncio.create_task(
                periodic_refresh_loop(settings.skillconnect_refresh_seconds)
            )
        log.info("SkillConnect catalog ready.")
    except Exception as exc:
        log.warning("SkillConnect catalog init failed (resolution degraded): %s", exc)

    try:
        yield
    finally:
        if catalog_task is not None:
            catalog_task.cancel()


def create_app() -> FastAPI:
    """Create FastAPI application."""

    configure_logging()
    app = FastAPI(
        title="CV Intelligence Layer API",
        version="1.0.0",
        default_response_class=UTF8JSONResponse,
        lifespan=lifespan,
    )
    app.include_router(api_router)

    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        should_group_status_codes=True,
        should_group_untemplated=True,
        excluded_handlers=["/health", "/ready", "/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()

