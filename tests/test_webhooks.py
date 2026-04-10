"""Tests for webhook receiver, signing, and ingestion webhook service."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.database import CVProfile
from app.models.schemas import (
    HPCallbackPayload,
    IngestedDocumentResult,
    IngestionWebhookPayload,
)
from app.services.ingestion_webhook_service import IngestionWebhookService
from app.utils.webhook_signing import sign_payload, verify_signature


# ---------------------------------------------------------------------------
# HMAC signing / verification
# ---------------------------------------------------------------------------


class TestWebhookSigning:
    def test_sign_payload(self) -> None:
        payload = b'{"event":"ingestion.completed"}'
        sig = sign_payload(payload, "test_secret")
        assert sig.startswith("sha256=")
        assert len(sig) == 71  # sha256= + 64 hex chars

    def test_verify_signature_valid(self) -> None:
        payload = b'{"event":"ingestion.completed"}'
        sig = sign_payload(payload, "test_secret")
        verify_signature(sig, payload, "test_secret")

    def test_verify_signature_invalid(self) -> None:
        from fastapi import HTTPException

        payload = b'{"event":"ingestion.completed"}'
        with pytest.raises(HTTPException) as exc_info:
            verify_signature("sha256=invalid", payload, "test_secret")
        assert exc_info.value.status_code == 401

    def test_verify_signature_wrong_secret(self) -> None:
        from fastapi import HTTPException

        payload = b'{"event":"ingestion.completed"}'
        sig = sign_payload(payload, "correct_secret")
        with pytest.raises(HTTPException):
            verify_signature(sig, payload, "wrong_secret")

    def test_different_payloads_different_signatures(self) -> None:
        sig1 = sign_payload(b"payload1", "secret")
        sig2 = sign_payload(b"payload2", "secret")
        assert sig1 != sig2


# ---------------------------------------------------------------------------
# IngestionWebhookService
# ---------------------------------------------------------------------------


def _make_cv(
    *,
    cv_id: uuid.UUID | None = None,
    status: str = "indexing",
    search_ingest_job_id: str | None = None,
    callback_url: str | None = None,
    external_id: str | None = "EMP-001",
    file_hash: str = "abc123",
) -> CVProfile:
    now = datetime.now(timezone.utc)
    cv = CVProfile(
        cv_id=cv_id or uuid.uuid4(),
        collection_id=uuid.uuid4(),
        external_id=external_id,
        file_hash=file_hash,
        search_ingest_job_id=search_ingest_job_id,
        callback_url=callback_url,
        status=status,
        created_at=now,
        updated_at=now,
    )
    return cv


def _make_webhook_payload(
    *,
    job_id: uuid.UUID | None = None,
    status: str = "completed",
    doc_status: str = "indexed",
    doc_error: str | None = None,
) -> IngestionWebhookPayload:
    jid = job_id or uuid.uuid4()
    return IngestionWebhookPayload(
        event="ingestion.completed",
        job_id=jid,
        collection_id=uuid.uuid4(),
        status=status,  # type: ignore[arg-type]
        total_docs=1,
        processed_docs=1 if doc_status == "indexed" else 0,
        failed_docs=0 if doc_status == "indexed" else 1,
        documents=[
            IngestedDocumentResult(
                external_id="abc123",
                status=doc_status,  # type: ignore[arg-type]
                error=doc_error,
            ),
        ],
        completed_at=datetime.now(timezone.utc),
    )


class TestIngestionWebhookService:
    @pytest.fixture()
    def service(self) -> IngestionWebhookService:
        return IngestionWebhookService()

    @pytest.mark.asyncio
    async def test_handle_success(self, service: IngestionWebhookService) -> None:
        """Completed ingest sets CV status to 'ready'."""
        ingest_job_id = uuid.uuid4()
        cv = _make_cv(search_ingest_job_id=str(ingest_job_id), callback_url=None)
        payload = _make_webhook_payload(job_id=ingest_job_id, status="completed")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cv
        mock_db.execute.return_value = mock_result

        await service.handle(db=mock_db, payload=payload)

        # Should have called execute 3 times: SELECT + UPDATE CVProfile + UPDATE CVProcessingJob
        assert mock_db.execute.call_count == 3
        assert mock_db.commit.call_count == 1

    @pytest.mark.asyncio
    async def test_handle_failure(self, service: IngestionWebhookService) -> None:
        """Failed ingest sets CV status to 'index_failed'."""
        ingest_job_id = uuid.uuid4()
        cv = _make_cv(search_ingest_job_id=str(ingest_job_id))
        payload = _make_webhook_payload(
            job_id=ingest_job_id,
            status="completed_with_errors",
            doc_status="failed",
            doc_error="Embedding timed out",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cv
        mock_db.execute.return_value = mock_result

        await service.handle(db=mock_db, payload=payload)

        assert mock_db.execute.call_count == 3
        assert mock_db.commit.call_count == 1

    @pytest.mark.asyncio
    async def test_handle_unknown_job_id(self, service: IngestionWebhookService) -> None:
        """Unknown ingest job_id is silently ignored."""
        payload = _make_webhook_payload(job_id=uuid.uuid4())

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        await service.handle(db=mock_db, payload=payload)

        # Only 1 SELECT, no UPDATE, no commit
        assert mock_db.execute.call_count == 1
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_idempotent_ready(self, service: IngestionWebhookService) -> None:
        """Already-finalized CVs are skipped."""
        ingest_job_id = uuid.uuid4()
        cv = _make_cv(
            search_ingest_job_id=str(ingest_job_id),
            status="ready",
        )
        payload = _make_webhook_payload(job_id=ingest_job_id)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cv
        mock_db.execute.return_value = mock_result

        await service.handle(db=mock_db, payload=payload)

        # Only 1 SELECT, no UPDATE
        assert mock_db.execute.call_count == 1
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_fires_hp_callback(self, service: IngestionWebhookService) -> None:
        """When callback_url exists, schedules Celery task for HP notification."""
        ingest_job_id = uuid.uuid4()
        cv = _make_cv(
            search_ingest_job_id=str(ingest_job_id),
            callback_url="https://hiring-platform.example.com/webhooks/cv",
        )
        payload = _make_webhook_payload(job_id=ingest_job_id, status="completed")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cv
        mock_db.execute.return_value = mock_result

        with patch(
            "app.tasks.ingestion.notify_hiring_platform"
        ) as mock_notify:
            mock_notify.apply_async = MagicMock()
            await service.handle(db=mock_db, payload=payload)
            mock_notify.apply_async.assert_called_once()

            call_args = mock_notify.apply_async.call_args
            args = call_args[1]["args"]
            assert args[0] == "https://hiring-platform.example.com/webhooks/cv"
            # Verify the payload is valid JSON
            hp_payload = json.loads(args[1])
            assert hp_payload["status"] == "ready"
            assert hp_payload["external_id"] == "EMP-001"

    @pytest.mark.asyncio
    async def test_handle_no_callback_when_url_missing(
        self, service: IngestionWebhookService
    ) -> None:
        """No HP callback if callback_url is None."""
        ingest_job_id = uuid.uuid4()
        cv = _make_cv(
            search_ingest_job_id=str(ingest_job_id),
            callback_url=None,
        )
        payload = _make_webhook_payload(job_id=ingest_job_id)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cv
        mock_db.execute.return_value = mock_result

        with patch(
            "app.tasks.ingestion.notify_hiring_platform"
        ) as mock_notify:
            await service.handle(db=mock_db, payload=payload)
            mock_notify.apply_async.assert_not_called()


# ---------------------------------------------------------------------------
# HPCallbackPayload schema
# ---------------------------------------------------------------------------


class TestHPCallbackPayload:
    def test_success_payload(self) -> None:
        p = HPCallbackPayload(
            external_id="EMP-001",
            file_hash="abc123",
            status="ready",
            completed_at=datetime.now(timezone.utc),
        )
        data = json.loads(p.model_dump_json())
        assert data["status"] == "ready"
        assert data["error"] is None

    def test_failure_payload(self) -> None:
        p = HPCallbackPayload(
            external_id="EMP-001",
            file_hash="abc123",
            status="index_failed",
            error="Embedding timed out",
            completed_at=datetime.now(timezone.utc),
        )
        data = json.loads(p.model_dump_json())
        assert data["status"] == "index_failed"
        assert data["error"] == "Embedding timed out"
