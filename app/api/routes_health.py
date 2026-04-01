from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.models.database import engine
from app.services.search_client import get_search_client

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness probe."""

    return {"status": "ok"}


@router.get("/ready")
async def readiness_check() -> dict[str, str]:
    """Readiness probe: checks DB + Semantic Search connectivity."""

    # DB
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    # Semantic search
    client = get_search_client()
    try:
        await client.list_collections(limit=1, offset=0)
    finally:
        await client.aclose()

    return {"status": "ready"}

