"""Webhook receiver endpoints for external service callbacks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_api_key
from app.models.database import get_db
from app.models.schemas import IngestionWebhookPayload
from app.services.ingestion_webhook_service import get_ingestion_webhook_service

router = APIRouter()


@router.post("/api/webhooks/ingestion", status_code=200)
async def ingestion_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_api_key),
) -> dict[str, bool]:
    """Receive ingestion completion webhook from Semantic Search.

    Authenticated via Bearer APP_API_KEY — same as all other CV layer
    endpoints.
    """
    raw_body = await request.body()
    payload = IngestionWebhookPayload.model_validate_json(raw_body)

    service = get_ingestion_webhook_service()
    await service.handle(db=db, payload=payload)

    return {"received": True}
