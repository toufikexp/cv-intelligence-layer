from __future__ import annotations

from fastapi import FastAPI

from app.api.router import api_router
from app.utils.logging import configure_logging


def create_app() -> FastAPI:
    """Create FastAPI application."""

    configure_logging()
    app = FastAPI(title="CV Intelligence Layer API", version="1.0.0")
    app.include_router(api_router)
    return app


app = create_app()

