"""Webhook receiver endpoints for external service callbacks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.models.schemas import IngestionWebhookPayload
from app.services.ingestion_webhook_service import get_ingestion_webhook_service
from app.utils.webhook_signing import verify_signature

router = APIRouter()


@router.post("/api/webhooks/ingestion", status_code=200)
async def ingestion_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_webhook_signature: str = Header(..., alias="X-Webhook-Signature"),
) -> dict[str, bool]:
    """Receive ingestion completion webhook from Semantic Search.

    Verifies HMAC-SHA256 signature, then delegates to the service layer
    to correlate the result, update CV status, and fire HP callback.
    """
    settings = get_settings()
    raw_body = await request.body()

    # Verify the signature from Semantic Search
    verify_signature(x_webhook_signature, raw_body, settings.search_webhook_secret)

    # Parse the validated body
    payload = IngestionWebhookPayload.model_validate_json(raw_body)

    # Process the webhook
    service = get_ingestion_webhook_service()
    await service.handle(db=db, payload=payload)

    return {"received": True}
