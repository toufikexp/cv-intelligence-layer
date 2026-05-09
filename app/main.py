from __future__ import annotations

import json
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


def create_app() -> FastAPI:
    """Create FastAPI application."""

    configure_logging()
    app = FastAPI(
        title="CV Intelligence Layer API",
        version="1.0.0",
        default_response_class=UTF8JSONResponse,
    )
    app.include_router(api_router)
    return app


app = create_app()

