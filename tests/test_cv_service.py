"""Tests for CV service CRUD operations."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.database import CVProcessingJob, CVProfile
from app.models.schemas import CandidateProfile
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


# ---------------------------------------------------------------------------
# reset_cv_for_reingest (PUT support)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_cv_for_reingest_wipes_derived_fields_and_creates_job() -> None:
    cv = CVProfile(
        cv_id=uuid.uuid4(),
        external_id="EMP-001",
        collection_id=uuid.uuid4(),
        file_hash="oldhash",
        status="ready",
        profile_data={"name": "Amina"},
        raw_text="old text",
        language="fra",
        extraction_method="text_extraction",
        candidate_name="Amina",
        email="amina@example.com",
        phone="+212600000000",
        search_ingest_job_id="old-ingest-job",
        search_doc_external_id="EMP-001",
    )
    mock_db = AsyncMock()
    svc = CVService()

    new_cv, new_job = await svc.reset_cv_for_reingest(
        db=mock_db,
        cv=cv,
        new_file_hash="newhash",
    )

    assert new_cv is cv
    assert cv.file_hash == "newhash"
    assert cv.status == "pending"
    assert cv.profile_data is None
    assert cv.raw_text is None
    assert cv.language is None
    assert cv.extraction_method is None
    assert cv.candidate_name is None
    assert cv.email is None
    assert cv.phone is None
    assert cv.search_ingest_job_id is None
    # Identity preserved
    assert cv.external_id == "EMP-001"
    assert cv.search_doc_external_id == "EMP-001"

    assert isinstance(new_job, CVProcessingJob)
    assert new_job.cv_id == cv.cv_id
    assert new_job.stage == "validate_file"
    assert new_job.status == "pending"
    assert new_job.progress_pct == 0

    mock_db.add.assert_called_once_with(new_job)
    mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# check_file_hash_conflict (PUT pre-check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_file_hash_conflict_raises_409_on_collision() -> None:
    existing = MagicMock(spec=CVProfile)
    existing.cv_id = uuid.uuid4()
    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = existing
    mock_db.execute = AsyncMock(return_value=exec_result)

    svc = CVService()
    with pytest.raises(HTTPException) as exc_info:
        await svc.check_file_hash_conflict(
            db=mock_db,
            collection_id=uuid.uuid4(),
            file_hash="dupehash",
            exclude_cv_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DUPLICATE_FILE"
    assert exc_info.value.detail["detail"] == str(existing.cv_id)


@pytest.mark.asyncio
async def test_check_file_hash_conflict_no_collision_returns_none() -> None:
    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=exec_result)

    svc = CVService()
    # Should not raise.
    await svc.check_file_hash_conflict(
        db=mock_db,
        collection_id=uuid.uuid4(),
        file_hash="uniquehash",
        exclude_cv_id=uuid.uuid4(),
    )


# ---------------------------------------------------------------------------
# update_profile_data (PATCH support)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_profile_data_writes_profile_and_denormalized_fields() -> None:
    cv = CVProfile(
        cv_id=uuid.uuid4(),
        external_id="EMP-001",
        collection_id=uuid.uuid4(),
        file_hash="h",
        status="ready",
        profile_data={"name": "Old Name"},
        candidate_name="Old Name",
        email="old@example.com",
        phone="+10000000000",
    )
    merged = CandidateProfile(
        name="New Name",
        email="new@example.com",
        phone="+20000000000",
        skills=["Python", "Spark"],
    )
    mock_db = AsyncMock()

    svc = CVService()
    result = await svc.update_profile_data(db=mock_db, cv=cv, merged_profile=merged)

    assert result is cv
    assert cv.profile_data["name"] == "New Name"
    assert cv.profile_data["skills"] == ["Python", "Spark"]
    assert cv.candidate_name == "New Name"
    assert cv.email == "new@example.com"
    assert cv.phone == "+20000000000"
    mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# check_email_conflict (PATCH pre-check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_email_conflict_raises_409_on_collision() -> None:
    existing = MagicMock(spec=CVProfile)
    existing.cv_id = uuid.uuid4()
    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = existing
    mock_db.execute = AsyncMock(return_value=exec_result)

    svc = CVService()
    with pytest.raises(HTTPException) as exc_info:
        await svc.check_email_conflict(
            db=mock_db,
            collection_id=uuid.uuid4(),
            email="dupe@example.com",
            exclude_cv_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DUPLICATE_EMAIL"


@pytest.mark.asyncio
async def test_mark_index_failed_sets_status_and_commits() -> None:
    cv = CVProfile(
        cv_id=uuid.uuid4(),
        external_id="EMP-001",
        collection_id=uuid.uuid4(),
        file_hash="h",
        status="ready",
    )
    mock_db = AsyncMock()

    svc = CVService()
    await svc.mark_index_failed(db=mock_db, cv=cv)

    assert cv.status == "index_failed"
    mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# create_ready_cv (POST /candidates JSON-create)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_ready_cv_success() -> None:
    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=exec_result)

    profile = CandidateProfile(
        name="Amina Bensaid",
        email="amina@example.com",
        skills=["Python", "Spark"],
    )

    svc = CVService()
    cv, job = await svc.create_ready_cv(
        db=mock_db,
        collection_id=uuid.uuid4(),
        external_id="EMP-100",
        file_hash="abc123",
        profile=profile,
        raw_text="Name: Amina Bensaid\nSkills: Python, Spark",
        language="fr",
    )

    assert cv.status == "ready"
    assert cv.external_id == "EMP-100"
    assert cv.file_hash == "abc123"
    assert cv.extraction_method == "json_input"
    assert cv.candidate_name == "Amina Bensaid"
    assert cv.email == "amina@example.com"
    assert cv.raw_text == "Name: Amina Bensaid\nSkills: Python, Spark"
    assert cv.language == "fr"
    assert cv.profile_data["skills"] == ["Python", "Spark"]
    assert cv.search_doc_external_id == "EMP-100"

    assert job.stage == "completed"
    assert job.status == "completed"
    assert job.progress_pct == 100
    assert job.completed_at is not None

    mock_db.add.assert_called()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_ready_cv_duplicate_external_id_raises_409() -> None:
    existing = MagicMock(spec=CVProfile)
    existing.cv_id = uuid.uuid4()

    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = existing
    mock_db.execute = AsyncMock(return_value=exec_result)

    svc = CVService()
    with pytest.raises(HTTPException) as exc_info:
        await svc.create_ready_cv(
            db=mock_db,
            collection_id=uuid.uuid4(),
            external_id="EMP-DUPE",
            file_hash="h",
            profile=CandidateProfile(name="X"),
            raw_text="text",
            language="en",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DUPLICATE_EXTERNAL_ID"


@pytest.mark.asyncio
async def test_create_ready_cv_duplicate_file_hash_raises_409() -> None:
    existing = MagicMock(spec=CVProfile)
    existing.cv_id = uuid.uuid4()

    ext_none = MagicMock()
    ext_none.scalar_one_or_none.return_value = None
    hash_hit = MagicMock()
    hash_hit.scalar_one_or_none.return_value = existing

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[ext_none, hash_hit])

    svc = CVService()
    with pytest.raises(HTTPException) as exc_info:
        await svc.create_ready_cv(
            db=mock_db,
            collection_id=uuid.uuid4(),
            external_id="EMP-NEW",
            file_hash="dupe_hash",
            profile=CandidateProfile(name="X"),
            raw_text="text",
            language="en",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DUPLICATE_FILE"
