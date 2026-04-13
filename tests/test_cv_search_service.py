"""Unit tests for CV search → Semantic Search mapping."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.database import CVProfile
from app.models.schemas import CVSearchRequest
from app.services.cv_search import CVSearchService


class _FakeSearchClient:
    async def search(self, **kwargs: object) -> dict:
        return {
            "results": [{"external_id": "deadbeef", "score": 0.91}],
            "total": 1,
        }


@pytest.mark.asyncio
async def test_cv_search_maps_file_hash_to_cv_id() -> None:
    cid = uuid.uuid4()
    cv_pk = uuid.uuid4()
    now = datetime.now(timezone.utc)
    cv = CVProfile(
        cv_id=cv_pk,
        external_id="deadbeef",
        collection_id=cid,
        file_hash="deadbeef",
        candidate_name="Test User",
        status="ready",
        created_at=now,
        updated_at=now,
    )

    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [cv]
    mock_db.execute = AsyncMock(return_value=exec_result)

    svc = CVSearchService()
    out = await svc.search(
        db=mock_db,
        client=_FakeSearchClient(),
        req=CVSearchRequest(collection_id=cid, query="engineer"),
    )

    assert len(out.results) == 1
    assert out.results[0].cv_id == cv_pk
    assert out.results[0].external_id == "deadbeef"
    assert out.results[0].score == pytest.approx(0.91)
    assert out.total == 1
    assert out.took_ms >= 0
