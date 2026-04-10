"""Handles incoming ingestion webhooks from Semantic Search."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import CVProcessingJob, CVProfile
from app.models.schemas import HPCallbackPayload, IngestionWebhookPayload

logger = logging.getLogger(__name__)


class IngestionWebhookService:
    """Process ingestion webhooks and fire HP callbacks."""

    async def handle(self, *, db: AsyncSession, payload: IngestionWebhookPayload) -> None:
        """Correlate by ``job_id``, update CV status, fire HP callback."""

        # 1. Look up the CV by the Semantic Search ingest job_id
        res = await db.execute(
            select(CVProfile).where(
                CVProfile.search_ingest_job_id == str(payload.job_id)
            )
        )
        cv = res.scalar_one_or_none()
        if not cv:
            logger.warning(
                "webhook.unknown_job_id job_id=%s collection_id=%s",
                payload.job_id,
                payload.collection_id,
            )
            return

        # 2. Idempotency — skip if already finalized
        if cv.status in ("ready", "index_failed"):
            logger.info(
                "webhook.already_finalized cv_id=%s status=%s",
                cv.cv_id,
                cv.status,
            )
            return

        # 3. Determine final status from the request-level status
        if payload.status == "completed":
            new_status = "ready"
            error = None
        else:
            new_status = "index_failed"
            failed_doc = next(
                (d for d in payload.documents if d.status == "failed"), None
            )
            error = failed_doc.error if failed_doc else "indexing failed"

        # 4. Update CV profile status
        now = datetime.utcnow()
        await db.execute(
            update(CVProfile)
            .where(CVProfile.cv_id == cv.cv_id)
            .values(status=new_status, updated_at=now)
        )

        # 5. Update processing job record
        await db.execute(
            update(CVProcessingJob)
            .where(CVProcessingJob.cv_id == cv.cv_id)
            .values(
                stage="finalize",
                status="completed" if new_status == "ready" else "failed",
                error_message=error,
                progress_pct=100,
                completed_at=now,
                updated_at=now,
            )
        )
        await db.commit()

        logger.info(
            "webhook.processed cv_id=%s new_status=%s ingest_job_id=%s",
            cv.cv_id,
            new_status,
            payload.job_id,
        )

        # 6. Fire callback to Hiring Platform (if callback_url was provided)
        if cv.callback_url:
            self._schedule_hp_callback(
                callback_url=cv.callback_url,
                external_id=cv.external_id,
                file_hash=cv.file_hash,
                status=new_status,
                error=error,
                completed_at=payload.completed_at,
            )

    def _schedule_hp_callback(
        self,
        *,
        callback_url: str,
        external_id: str | None,
        file_hash: str,
        status: str,
        error: str | None,
        completed_at: datetime,
    ) -> None:
        """Dispatch callback to Hiring Platform via Celery task."""
        from app.tasks.ingestion import notify_hiring_platform

        cb = HPCallbackPayload(
            external_id=external_id,
            file_hash=file_hash,
            status=status,  # type: ignore[arg-type]
            error=error,
            completed_at=completed_at,
        )
        notify_hiring_platform.apply_async(
            args=[callback_url, cb.model_dump_json()],
        )


_service: IngestionWebhookService | None = None


def get_ingestion_webhook_service() -> IngestionWebhookService:
    global _service
    if _service is None:
        _service = IngestionWebhookService()
    return _service
