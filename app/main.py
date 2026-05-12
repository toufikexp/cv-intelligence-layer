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
    """Pre-warm the EasyOCR model so the first OCR request doesn't pay cold-start."""
    log = logging.getLogger("cv_layer.startup")
    try:
        from app.services.ocr_service import _get_reader

        log.info("Pre-warming EasyOCR model…")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _get_reader)
        log.info("EasyOCR model ready.")
    except Exception as exc:  # never block startup on a pre-warm failure
        log.warning("OCR pre-warm failed (will load on first request): %s", exc)
    yield


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
    return app


app = create_app()

