"""Webhook receiver endpoints for external service callbacks."""

from __future__ import annotations

import json

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
    x_webhook_signature: str = Header(),
) -> dict[str, bool]:
    """Receive ingestion completion webhook from Semantic Search.

    Authenticated via HMAC-SHA256 signature in X-Webhook-Signature header,
    verified against SEARCH_WEBHOOK_SECRET.
    """
    raw_body = await request.body()
    # The Semantic Search signs json.dumps(payload, sort_keys=True) but sends
    # via httpx json= which re-serializes without sort_keys. Re-sort to match.
    sorted_body = json.dumps(json.loads(raw_body), sort_keys=True).encode()
    verify_signature(x_webhook_signature, sorted_body, get_settings().search_webhook_secret)
    payload = IngestionWebhookPayload.model_validate_json(raw_body)

    service = get_ingestion_webhook_service()
    await service.handle(db=db, payload=payload)

    return {"received": True}
