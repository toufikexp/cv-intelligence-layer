"""Tests for CV service CRUD operations."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.database import CVProfile
from app.services.cv_service import CVService


@pytest.mark.asyncio
async def test_create_pending_cv_success() -> None:
    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=exec_result)

    svc = CVService()
    cv, job = await svc.create_pending_cv(
        db=mock_db,
        collection_id=uuid.uuid4(),
        external_id="ext-1",
        file_hash="deadbeef123",
    )

    assert cv.status == "pending"
    assert cv.file_hash == "deadbeef123"
    assert job.stage == "validate_file"
    assert job.status == "pending"
    mock_db.add.assert_called()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_pending_cv_duplicate_external_id_raises_409() -> None:
    existing = MagicMock(spec=CVProfile)
    existing.cv_id = uuid.uuid4()

    # The external_id check is the first lookup and returns a match.
    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = existing
    mock_db.execute = AsyncMock(return_value=exec_result)

    svc = CVService()
    with pytest.raises(HTTPException) as exc_info:
        await svc.create_pending_cv(
            db=mock_db,
            collection_id=uuid.uuid4(),
            external_id="EMP-001",
            file_hash="same_hash",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DUPLICATE_EXTERNAL_ID"


@pytest.mark.asyncio
async def test_create_pending_cv_duplicate_file_hash_raises_409() -> None:
    existing = MagicMock(spec=CVProfile)
    existing.cv_id = uuid.uuid4()

    # First call (external_id check) finds nothing, second call (file_hash
    # check) finds a match.
    ext_none = MagicMock()
    ext_none.scalar_one_or_none.return_value = None
    hash_hit = MagicMock()
    hash_hit.scalar_one_or_none.return_value = existing

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[ext_none, hash_hit])

    svc = CVService()
    with pytest.raises(HTTPException) as exc_info:
        await svc.create_pending_cv(
            db=mock_db,
            collection_id=uuid.uuid4(),
            external_id="EMP-002",
            file_hash="same_hash",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DUPLICATE_FILE"


@pytest.mark.asyncio
async def test_get_cv_not_found_raises_404() -> None:
    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=exec_result)

    svc = CVService()
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_cv(db=mock_db, cv_id=uuid.uuid4())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_cv_found() -> None:
    cv = MagicMock(spec=CVProfile)
    cv.cv_id = uuid.uuid4()

    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = cv
    mock_db.execute = AsyncMock(return_value=exec_result)

    svc = CVService()
    result = await svc.get_cv(db=mock_db, cv_id=cv.cv_id)
    assert result.cv_id == cv.cv_id


@pytest.mark.asyncio
async def test_get_cv_by_external_id_found() -> None:
    cv = MagicMock(spec=CVProfile)
    cv.cv_id = uuid.uuid4()
    cv.external_id = "EMP-001"

    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = cv
    mock_db.execute = AsyncMock(return_value=exec_result)

    svc = CVService()
    result = await svc.get_cv_by_external_id(
        db=mock_db,
        collection_id=uuid.uuid4(),
        external_id="EMP-001",
    )
    assert result.cv_id == cv.cv_id
    assert result.external_id == "EMP-001"


@pytest.mark.asyncio
async def test_get_cv_by_external_id_not_found_raises_404() -> None:
    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=exec_result)

    svc = CVService()
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_cv_by_external_id(
            db=mock_db,
            collection_id=uuid.uuid4(),
            external_id="DOES-NOT-EXIST",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "NOT_FOUND"
