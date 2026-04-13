from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_api_key
from app.models.database import get_db
from app.models.schemas import (
    CVProfileResponse,
    CVSearchRequest,
    CVSearchResponse,
    CVStatusEnum,
    CVStatusResponse,
    CVUploadResponse,
    CandidateProfile,
)
from app.services.cv_search import get_cv_search_service
from app.services.cv_service import CVService, get_cv_service
from app.services.search_client import get_ingest_search_client, get_search_client
from app.tasks.ingestion import start_cv_ingestion
from app.utils.file_validation import validate_and_persist_upload

router = APIRouter()

ProfileStatus = Literal["pending", "extracting", "indexing", "ready", "failed", "index_failed"]


def _narrow_profile_status(status: str) -> ProfileStatus:
    """Map internal pipeline statuses to OpenAPI CVProfileResponse status enum."""
    if status in ("ocr_processing", "entity_extraction"):
        return "extracting"
    if status in ("pending", "extracting", "indexing", "ready", "failed", "index_failed"):
        return status  # type: ignore[return-value]
    return "extracting"


def _stage_to_cv_status(stage: str | None) -> CVStatusEnum:
    m: dict[str, CVStatusEnum] = {
        "validate_file": "pending",
        "extract_text": "extracting",
        "ocr": "ocr_processing",
        "detect_language": "extracting",
        "entity_extraction": "entity_extraction",
        "indexing": "indexing",
    }
    return m.get(stage or "", "pending")


@router.post("/candidates/upload", status_code=202, response_model=CVUploadResponse)
async def upload_cv(
    file: UploadFile = File(...),
    collection_id: uuid.UUID = Form(...),
    external_id: str = Form(..., min_length=1, max_length=255),
    callback_url: str | None = Form(default=None),
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVUploadResponse:
    path, file_hash = await validate_and_persist_upload(file)

    cv, job = await cv_service.create_pending_cv(
        db=db,
        collection_id=collection_id,
        external_id=external_id,
        file_hash=file_hash,
        callback_url=callback_url,
    )

    start_cv_ingestion(
        cv_id=cv.cv_id,
        job_id=job.job_id,
        collection_id=collection_id,
        file_hash=file_hash,
        file_path=str(path),
        mime=file.content_type or "",
    )
    return CVUploadResponse(cv_id=cv.cv_id, job_id=job.job_id, status="pending", file_hash=file_hash)


@router.get("/candidates/{cv_id}", response_model=CVProfileResponse)
async def get_cv(
    cv_id: uuid.UUID,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVProfileResponse:
    cv = await cv_service.get_cv(db=db, cv_id=cv_id)
    profile: CandidateProfile | None = None
    if cv.profile_data:
        profile = CandidateProfile.model_validate(cv.profile_data, strict=False)
    return CVProfileResponse(
        cv_id=cv.cv_id,
        external_id=cv.external_id,
        collection_id=cv.collection_id,
        status=_narrow_profile_status(cv.status),
        language=cv.language,
        extraction_method=cv.extraction_method,
        profile=profile,
        created_at=cv.created_at,
        updated_at=cv.updated_at,
    )


@router.get("/candidates/{cv_id}/status", response_model=CVStatusResponse)
async def get_cv_status(
    cv_id: uuid.UUID,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVStatusResponse:
    cv = await cv_service.get_cv(db=db, cv_id=cv_id)
    job = await cv_service.get_latest_processing_job(db=db, cv_id=cv_id)

    if cv.status == "ready":
        api_status: CVStatusEnum = "ready"
    elif cv.status in ("failed", "index_failed"):
        api_status = cv.status  # type: ignore[assignment]
    elif job and job.status != "completed":
        api_status = _stage_to_cv_status(job.stage)
    else:
        api_status = _stage_to_cv_status(job.stage if job else None)

    return CVStatusResponse(
        cv_id=cv.cv_id,
        status=api_status,
        current_stage=job.stage if job else None,
        error_message=job.error_message if job else None,
        progress_pct=job.progress_pct if job else None,
        created_at=job.created_at if job else None,
        completed_at=job.completed_at if job else None,
    )


@router.delete("/candidates/{cv_id}", status_code=204)
async def delete_cv(
    cv_id: uuid.UUID,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> None:
    cv = await cv_service.get_cv(db=db, cv_id=cv_id)
    external_id = cv.search_doc_external_id or cv.file_hash
    client = get_ingest_search_client()
    try:
        await client.delete_document_if_exists(
            collection_id=cv.collection_id,
            external_id=external_id,
        )
    finally:
        await client.aclose()
    await cv_service.delete_cv(db=db, cv_id=cv_id)
    return None


@router.post("/candidates/search", response_model=CVSearchResponse)
async def search_cvs(
    req: CVSearchRequest,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
) -> CVSearchResponse:
    client = get_search_client()
    try:
        return await get_cv_search_service().search(db=db, client=client, req=req)
    finally:
        await client.aclose()
