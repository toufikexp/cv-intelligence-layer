"""Tests for the PUT, PATCH, and POST (JSON-create) helper flows in app/api/cv.py.

These exercise ``_replace_cv_file``, ``_apply_profile_patch``, and
``create_cv_from_json`` directly instead of going through ``TestClient``
because the dependency graph (search client, Celery, file validation) is
easier to stub at the helper boundary than via FastAPI's override system.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Response

from app.api.cv import (
    _apply_profile_patch,
    _replace_cv_file,
    create_cv_from_json,
    extract_cv,
)
from app.models.database import CVProcessingJob, CVProfile
from app.models.schemas import CandidateCreateRequest, CandidateProfile, CandidateProfilePatch
from app.services.cv_service import CVService
from app.services.document_processor import ExtractedText
from app.services.indexing_bridge import build_synthetic_text


def _ready_cv(**overrides: object) -> CVProfile:
    now = datetime.now(timezone.utc)
    defaults: dict[str, object] = dict(
        cv_id=uuid.uuid4(),
        external_id="EMP-001",
        collection_id=uuid.uuid4(),
        file_hash="existing_hash",
        status="ready",
        language="fra",
        raw_text="Amina est ingénieure data.",
        created_at=now,
        updated_at=now,
        profile_data={
            "name": "Amina Bensaid",
            "email": "amina@example.com",
            "phone": "+212600000000",
            "skills": ["Python"],
            "experience": [],
            "education": [],
            "languages": [],
            "certifications": [],
        },
        candidate_name="Amina Bensaid",
        email="amina@example.com",
        phone="+212600000000",
    )
    defaults.update(overrides)
    return CVProfile(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _replace_cv_file — PUT path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_cv_file_short_circuits_on_identical_bytes() -> None:
    cv = _ready_cv()
    cv_service = MagicMock(spec=CVService)
    latest_job = MagicMock(spec=CVProcessingJob)
    latest_job.job_id = uuid.uuid4()
    cv_service.get_latest_processing_job = AsyncMock(return_value=latest_job)
    # These MUST NOT be called on the no-change path.
    cv_service.check_file_hash_conflict = AsyncMock()
    cv_service.reset_cv_for_reingest = AsyncMock()

    mock_path = MagicMock(spec=Path)
    with (
        patch(
            "app.api.cv.validate_and_persist_upload",
            AsyncMock(return_value=(mock_path, "existing_hash")),
        ),
        patch("app.api.cv.start_cv_ingestion") as start_ingest,
    ):
        response = Response()
        upload = MagicMock()
        upload.content_type = "application/pdf"

        result = await _replace_cv_file(
            db=AsyncMock(),
            cv_service=cv_service,
            cv=cv,
            file=upload,
            callback_url=None,
            response=response,
        )

    assert response.status_code == 200
    assert result.no_change is True
    assert result.cv_id == cv.cv_id
    assert result.job_id == latest_job.job_id
    assert result.file_hash == "existing_hash"
    mock_path.unlink.assert_called_once_with(missing_ok=True)
    cv_service.reset_cv_for_reingest.assert_not_called()
    cv_service.check_file_hash_conflict.assert_not_called()
    start_ingest.assert_not_called()


@pytest.mark.asyncio
async def test_replace_cv_file_reingests_when_hash_differs() -> None:
    cv = _ready_cv()
    new_job = CVProcessingJob(
        job_id=uuid.uuid4(),
        cv_id=cv.cv_id,
        stage="validate_file",
        status="pending",
        progress_pct=0,
    )

    cv_service = MagicMock(spec=CVService)
    cv_service.check_file_hash_conflict = AsyncMock()
    cv_service.reset_cv_for_reingest = AsyncMock(return_value=(cv, new_job))

    new_path = Path("/tmp/replacement.pdf")
    with (
        patch(
            "app.api.cv.validate_and_persist_upload",
            AsyncMock(return_value=(new_path, "brand_new_hash")),
        ),
        patch("app.api.cv.start_cv_ingestion") as start_ingest,
    ):
        response = Response()
        upload = MagicMock()
        upload.content_type = "application/pdf"

        result = await _replace_cv_file(
            db=AsyncMock(),
            cv_service=cv_service,
            cv=cv,
            file=upload,
            callback_url="https://hp.example/hook",
            response=response,
        )

    assert response.status_code == 202
    assert result.no_change is False
    assert result.cv_id == cv.cv_id
    assert result.job_id == new_job.job_id
    assert result.file_hash == "brand_new_hash"
    assert result.status == "pending"
    # callback_url override was applied on the CV row
    assert cv.callback_url == "https://hp.example/hook"

    cv_service.check_file_hash_conflict.assert_awaited_once()
    cv_service.reset_cv_for_reingest.assert_awaited_once()
    start_ingest.assert_called_once()
    _, kwargs = start_ingest.call_args
    assert kwargs["cv_id"] == cv.cv_id
    assert kwargs["job_id"] == new_job.job_id
    assert kwargs["file_hash"] == "brand_new_hash"
    assert kwargs["file_path"] == str(new_path)
    assert kwargs["mime"] == "application/pdf"


@pytest.mark.asyncio
async def test_replace_cv_file_raises_409_on_hash_collision() -> None:
    cv = _ready_cv()
    cv_service = MagicMock(spec=CVService)
    other_cv_id = uuid.uuid4()
    cv_service.check_file_hash_conflict = AsyncMock(
        side_effect=HTTPException(
            status_code=409,
            detail={"detail": str(other_cv_id), "code": "DUPLICATE_FILE"},
        )
    )
    cv_service.reset_cv_for_reingest = AsyncMock()

    with (
        patch(
            "app.api.cv.validate_and_persist_upload",
            AsyncMock(return_value=(Path("/tmp/new.pdf"), "collides")),
        ),
        patch("app.api.cv.start_cv_ingestion") as start_ingest,
    ):
        upload = MagicMock()
        upload.content_type = "application/pdf"

        with pytest.raises(HTTPException) as exc_info:
            await _replace_cv_file(
                db=AsyncMock(),
                cv_service=cv_service,
                cv=cv,
                file=upload,
                callback_url=None,
                response=Response(),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DUPLICATE_FILE"
    cv_service.reset_cv_for_reingest.assert_not_called()
    start_ingest.assert_not_called()


# ---------------------------------------------------------------------------
# _apply_profile_patch — PATCH path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_profile_patch_rejects_non_ready_cv() -> None:
    cv = _ready_cv(status="extracting")
    cv_service = MagicMock(spec=CVService)

    with pytest.raises(HTTPException) as exc_info:
        await _apply_profile_patch(
            db=AsyncMock(),
            cv_service=cv_service,
            cv=cv,
            patch=CandidateProfilePatch(current_title="Staff Engineer"),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "CV_NOT_READY"


@pytest.mark.asyncio
async def test_apply_profile_patch_rejects_when_profile_data_missing() -> None:
    cv = _ready_cv(status="ready", profile_data=None)
    cv_service = MagicMock(spec=CVService)

    with pytest.raises(HTTPException) as exc_info:
        await _apply_profile_patch(
            db=AsyncMock(),
            cv_service=cv_service,
            cv=cv,
            patch=CandidateProfilePatch(current_title="Staff Engineer"),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "CV_NOT_READY"


@pytest.mark.asyncio
async def test_apply_profile_patch_merges_and_reindexes_sync() -> None:
    cv = _ready_cv()
    cv_service = MagicMock(spec=CVService)
    cv_service.check_email_conflict = AsyncMock()
    cv_service.mark_index_failed = AsyncMock()

    async def _update_profile_data(*, db, cv, merged_profile):
        cv.profile_data = merged_profile.model_dump(mode="json")
        cv.candidate_name = merged_profile.name
        cv.email = merged_profile.email
        cv.phone = merged_profile.phone
        return cv

    cv_service.update_profile_data = AsyncMock(side_effect=_update_profile_data)

    mock_client = MagicMock()
    mock_client.ingest_documents = AsyncMock(return_value={"job_id": "stub"})
    mock_client.aclose = AsyncMock()

    with patch("app.api.cv.get_ingest_search_client", return_value=mock_client):
        result = await _apply_profile_patch(
            db=AsyncMock(),
            cv_service=cv_service,
            cv=cv,
            patch=CandidateProfilePatch(
                current_title="Senior Data Engineer",
                skills=["Python", "Spark", "Airflow"],
                certifications=["AWS SA"],
            ),
        )

    # Profile merge happened.
    assert cv.profile_data["current_title"] == "Senior Data Engineer"
    assert cv.profile_data["skills"] == ["Python", "Spark", "Airflow"]
    assert cv.profile_data["certifications"] == ["AWS SA"]
    # Untouched scalars preserved.
    assert cv.profile_data["email"] == "amina@example.com"
    assert cv.profile_data["name"] == "Amina Bensaid"

    # Email didn't change → no email conflict check.
    cv_service.check_email_conflict.assert_not_called()

    # Re-indexed once, with the existing external_id.
    mock_client.ingest_documents.assert_awaited_once()
    _, kwargs = mock_client.ingest_documents.call_args
    assert kwargs["upsert"] is True
    assert kwargs["collection_id"] == cv.collection_id
    assert len(kwargs["documents"]) == 1
    assert kwargs["documents"][0]["external_id"] == cv.external_id
    mock_client.aclose.assert_awaited_once()

    # Handler returned a well-formed CVProfileResponse.
    assert result.cv_id == cv.cv_id
    assert result.external_id == cv.external_id
    assert result.profile is not None
    assert result.profile.current_title == "Senior Data Engineer"


@pytest.mark.asyncio
async def test_apply_profile_patch_checks_email_conflict_when_email_changes() -> None:
    cv = _ready_cv()
    cv_service = MagicMock(spec=CVService)
    cv_service.check_email_conflict = AsyncMock(
        side_effect=HTTPException(
            status_code=409,
            detail={"detail": "email conflict", "code": "DUPLICATE_EMAIL"},
        )
    )
    cv_service.update_profile_data = AsyncMock()
    cv_service.mark_index_failed = AsyncMock()

    with patch("app.api.cv.get_ingest_search_client") as get_client:
        with pytest.raises(HTTPException) as exc_info:
            await _apply_profile_patch(
                db=AsyncMock(),
                cv_service=cv_service,
                cv=cv,
                patch=CandidateProfilePatch(email="new@example.com"),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DUPLICATE_EMAIL"
    cv_service.update_profile_data.assert_not_called()
    get_client.assert_not_called()


@pytest.mark.asyncio
async def test_apply_profile_patch_marks_index_failed_on_upstream_error() -> None:
    cv = _ready_cv()
    cv_service = MagicMock(spec=CVService)
    cv_service.check_email_conflict = AsyncMock()
    cv_service.update_profile_data = AsyncMock(return_value=cv)
    cv_service.mark_index_failed = AsyncMock()

    mock_client = MagicMock()
    mock_client.ingest_documents = AsyncMock(side_effect=RuntimeError("boom"))
    mock_client.aclose = AsyncMock()

    with patch("app.api.cv.get_ingest_search_client", return_value=mock_client):
        with pytest.raises(HTTPException) as exc_info:
            await _apply_profile_patch(
                db=AsyncMock(),
                cv_service=cv_service,
                cv=cv,
                patch=CandidateProfilePatch(current_title="Senior Data Engineer"),
            )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "UPSTREAM_SEARCH_ERROR"
    cv_service.mark_index_failed.assert_awaited_once()
    mock_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_profile_patch_rejects_unknown_fields() -> None:
    # Unknown fields should fail at Pydantic level, not reach the helper.
    with pytest.raises(Exception):  # ValidationError at model construction
        CandidateProfilePatch(not_a_real_field="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# create_cv_from_json — POST /candidates (JSON-create)
# ---------------------------------------------------------------------------


def _make_create_request(**overrides: object) -> CandidateCreateRequest:
    defaults: dict[str, object] = dict(
        collection_id=uuid.uuid4(),
        external_id="EMP-NEW",
        profile=CandidateProfile(
            name="Amina Bensaid",
            email="amina@example.com",
            skills=["Python", "Spark"],
        ),
    )
    defaults.update(overrides)
    return CandidateCreateRequest(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_create_cv_from_json_happy_path() -> None:
    req = _make_create_request()
    synthetic = build_synthetic_text(req.profile)
    expected_hash = hashlib.sha256(synthetic.encode()).hexdigest()

    now = datetime.now(timezone.utc)
    cv = CVProfile(
        cv_id=uuid.uuid4(),
        external_id=req.external_id,
        collection_id=req.collection_id,
        file_hash=expected_hash,
        status="indexing",
        profile_data=req.profile.model_dump(mode="json"),
        raw_text=synthetic,
        language="mixed",
        extraction_method="json_input",
        candidate_name=req.profile.name,
        email=req.profile.email,
        search_doc_external_id=req.external_id,
        created_at=now,
        updated_at=now,
    )
    job = CVProcessingJob(
        job_id=uuid.uuid4(),
        cv_id=cv.cv_id,
        stage="indexing",
        status="submitted",
        progress_pct=90,
    )

    cv_service = MagicMock(spec=CVService)
    cv_service.create_cv_for_indexing = AsyncMock(return_value=(cv, job))
    cv_service.mark_index_failed = AsyncMock()

    mock_db = AsyncMock()
    mock_client = MagicMock()
    mock_client.ingest_documents = AsyncMock(return_value={"job_id": "stub-job-id"})
    mock_client.aclose = AsyncMock()

    with (
        patch("app.api.cv.get_ingest_search_client", return_value=mock_client),
        patch("app.api.cv.detect_language", AsyncMock(return_value="mixed")),
        patch("app.api.cv.get_api_key", return_value="test-key"),
        patch("app.api.cv.get_cv_service", return_value=cv_service),
    ):
        result = await create_cv_from_json(
            req=req,
            _="test-key",
            db=mock_db,
            cv_service=cv_service,
        )

    assert result.cv_id == cv.cv_id
    assert result.external_id == req.external_id
    assert result.status == "indexing"
    assert cv.search_ingest_job_id == "stub-job-id"
    assert result.profile is not None
    assert result.profile.name == "Amina Bensaid"
    assert result.profile.skills == ["Python", "Spark"]

    cv_service.create_cv_for_indexing.assert_awaited_once()
    call_kwargs = cv_service.create_cv_for_indexing.call_args.kwargs
    assert call_kwargs["external_id"] == "EMP-NEW"
    assert call_kwargs["file_hash"] == expected_hash
    assert call_kwargs["raw_text"] == synthetic

    mock_client.ingest_documents.assert_awaited_once()
    _, ingest_kwargs = mock_client.ingest_documents.call_args
    assert ingest_kwargs["upsert"] is True
    assert ingest_kwargs["documents"][0]["external_id"] == req.external_id
    mock_client.aclose.assert_awaited_once()

    cv_service.mark_index_failed.assert_not_called()


@pytest.mark.asyncio
async def test_create_cv_from_json_search_failure_marks_index_failed() -> None:
    req = _make_create_request()
    synthetic = build_synthetic_text(req.profile)

    now = datetime.now(timezone.utc)
    cv = CVProfile(
        cv_id=uuid.uuid4(),
        external_id=req.external_id,
        collection_id=req.collection_id,
        file_hash="h",
        status="indexing",
        profile_data=req.profile.model_dump(mode="json"),
        raw_text=synthetic,
        language="mixed",
        extraction_method="json_input",
        candidate_name=req.profile.name,
        search_doc_external_id=req.external_id,
        created_at=now,
        updated_at=now,
    )
    job = CVProcessingJob(
        job_id=uuid.uuid4(),
        cv_id=cv.cv_id,
        stage="indexing",
        status="submitted",
        progress_pct=90,
    )

    cv_service = MagicMock(spec=CVService)
    cv_service.create_cv_for_indexing = AsyncMock(return_value=(cv, job))
    cv_service.mark_index_failed = AsyncMock()

    mock_client = MagicMock()
    mock_client.ingest_documents = AsyncMock(side_effect=RuntimeError("network down"))
    mock_client.aclose = AsyncMock()

    with (
        patch("app.api.cv.get_ingest_search_client", return_value=mock_client),
        patch("app.api.cv.detect_language", AsyncMock(return_value="mixed")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await create_cv_from_json(
                req=req,
                _="test-key",
                db=AsyncMock(),
                cv_service=cv_service,
            )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "UPSTREAM_SEARCH_ERROR"
    cv_service.mark_index_failed.assert_awaited_once()
    mock_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_cv_from_json_duplicate_external_id_raises_409() -> None:
    req = _make_create_request()

    cv_service = MagicMock(spec=CVService)
    cv_service.create_cv_for_indexing = AsyncMock(
        side_effect=HTTPException(
            status_code=409,
            detail={"detail": "external_id 'EMP-NEW' already exists", "code": "DUPLICATE_EXTERNAL_ID"},
        )
    )

    with (
        patch("app.api.cv.detect_language", AsyncMock(return_value="mixed")),
        patch("app.api.cv.get_ingest_search_client") as get_client,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await create_cv_from_json(
                req=req,
                _="test-key",
                db=AsyncMock(),
                cv_service=cv_service,
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DUPLICATE_EXTERNAL_ID"
    get_client.assert_not_called()


@pytest.mark.asyncio
async def test_create_cv_from_json_rejects_unknown_fields() -> None:
    with pytest.raises(Exception):
        CandidateCreateRequest(
            collection_id=uuid.uuid4(),
            external_id="EMP-X",
            profile=CandidateProfile(name="X"),
            bogus_field="should fail",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# extract_cv — POST /candidates/extract (stateless preview)
# ---------------------------------------------------------------------------


def _fake_upload(content_type: str = "application/pdf", filename: str = "cv.pdf") -> MagicMock:
    upload = MagicMock()
    upload.content_type = content_type
    upload.filename = filename
    return upload


def _extracted_profile() -> CandidateProfile:
    return CandidateProfile(
        name="Amina Bensaid",
        email="amina@example.com",
        skills=["Python", "Spark"],
    )


@pytest.mark.asyncio
async def test_extract_cv_happy_path_pdf() -> None:
    mock_path = MagicMock(spec=Path)
    profile = _extracted_profile()

    fake_processor = MagicMock()
    fake_processor.extract = AsyncMock(
        return_value=ExtractedText(
            text="Raw text from PDF.",
            method="text_extraction",
            needs_ocr=False,
        )
    )
    fake_extractor = MagicMock()
    fake_extractor.extract = AsyncMock(return_value=profile)

    with (
        patch(
            "app.api.cv.validate_and_persist_upload",
            AsyncMock(return_value=(mock_path, "filehash123")),
        ),
        patch("app.api.cv.DocumentProcessor", return_value=fake_processor),
        patch("app.api.cv.detect_language", AsyncMock(return_value="fr")),
        patch("app.api.cv.get_llm_client", return_value=MagicMock()),
        patch("app.api.cv.EntityExtractor", return_value=fake_extractor),
        patch("app.api.cv.ocr_pdf_pages") as ocr_mock,
    ):
        result = await extract_cv(file=_fake_upload(), _="test-key")

    assert result.profile.name == "Amina Bensaid"
    assert result.language == "fr"
    assert result.extraction_method == "text_extraction"
    assert result.file_hash == "filehash123"
    assert result.raw_text == "Raw text from PDF."
    # OCR branch was not taken.
    ocr_mock.assert_not_called()
    # Entity extractor was called with the non-OCR notes.
    fake_extractor.extract.assert_awaited_once()
    notes = fake_extractor.extract.call_args.kwargs["extraction_notes"]
    assert "OCR" not in notes
    # Stateless: temp file deleted.
    mock_path.unlink.assert_called_once_with(missing_ok=True)


@pytest.mark.asyncio
async def test_extract_cv_invalid_mime_returns_400() -> None:
    with patch(
        "app.api.cv.validate_and_persist_upload",
        AsyncMock(
            side_effect=HTTPException(
                status_code=400,
                detail={"detail": "Invalid file type", "code": "INVALID_FILE_TYPE"},
            )
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await extract_cv(file=_fake_upload(content_type="image/png"), _="test-key")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "INVALID_FILE_TYPE"


@pytest.mark.asyncio
async def test_extract_cv_file_too_large_returns_400() -> None:
    with patch(
        "app.api.cv.validate_and_persist_upload",
        AsyncMock(
            side_effect=HTTPException(
                status_code=400,
                detail={"detail": "File too large", "code": "FILE_TOO_LARGE"},
            )
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await extract_cv(file=_fake_upload(), _="test-key")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_extract_cv_llm_failure_returns_502_and_cleans_up() -> None:
    mock_path = MagicMock(spec=Path)

    fake_processor = MagicMock()
    fake_processor.extract = AsyncMock(
        return_value=ExtractedText(
            text="Raw text.",
            method="text_extraction",
            needs_ocr=False,
        )
    )
    fake_extractor = MagicMock()
    fake_extractor.extract = AsyncMock(side_effect=RuntimeError("Gemini empty response"))

    with (
        patch(
            "app.api.cv.validate_and_persist_upload",
            AsyncMock(return_value=(mock_path, "h")),
        ),
        patch("app.api.cv.DocumentProcessor", return_value=fake_processor),
        patch("app.api.cv.detect_language", AsyncMock(return_value="fr")),
        patch("app.api.cv.get_llm_client", return_value=MagicMock()),
        patch("app.api.cv.EntityExtractor", return_value=fake_extractor),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await extract_cv(file=_fake_upload(), _="test-key")

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "UPSTREAM_LLM_ERROR"
    # finally block ran: temp file cleaned up even on LLM failure.
    mock_path.unlink.assert_called_once_with(missing_ok=True)


@pytest.mark.asyncio
async def test_extract_cv_ocr_branch_invokes_ocr() -> None:
    mock_path = MagicMock(spec=Path)
    profile = _extracted_profile()

    fake_processor = MagicMock()
    fake_processor.extract = AsyncMock(
        return_value=ExtractedText(
            text="",  # sparse — triggers OCR
            method="text_extraction",
            needs_ocr=True,
        )
    )
    fake_extractor = MagicMock()
    fake_extractor.extract = AsyncMock(return_value=profile)

    with (
        patch(
            "app.api.cv.validate_and_persist_upload",
            AsyncMock(return_value=(mock_path, "h")),
        ),
        patch("app.api.cv.DocumentProcessor", return_value=fake_processor),
        patch("app.api.cv.detect_language", AsyncMock(return_value="fr")),
        patch("app.api.cv.get_llm_client", return_value=MagicMock()),
        patch("app.api.cv.EntityExtractor", return_value=fake_extractor),
        patch(
            "app.api.cv.ocr_pdf_pages",
            return_value=("OCR recovered text", "ocr_easyocr"),
        ) as ocr_mock,
    ):
        result = await extract_cv(file=_fake_upload(), _="test-key")

    ocr_mock.assert_called_once()
    assert result.extraction_method == "ocr_easyocr"
    assert result.raw_text == "OCR recovered text"
    # Entity extractor should have been told the text came from OCR.
    notes = fake_extractor.extract.call_args.kwargs["extraction_notes"]
    assert "OCR" in notes
    mock_path.unlink.assert_called_once_with(missing_ok=True)
