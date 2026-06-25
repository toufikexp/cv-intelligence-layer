from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_api_key
from app.config import get_settings
from app.models.database import CVProcessingJob, CVProfile, get_db
from app.models.schemas import (
    CandidateCreateRequest,
    CandidateProfile,
    CandidateProfilePatch,
    CVExtractionResponse,
    CVProfileResponse,
    CVSearchRequest,
    CVSearchResponse,
    CVStatusEnum,
    CVStatusResponse,
    CVUploadResponse,
)
from app.services.catalog_store import catalog_store
from app.services.cv_search import get_cv_search_service
from app.services.cv_service import CVService, get_cv_service
from app.services.document_processor import DocumentProcessor
from app.services.entity_extractor import EntityExtractor, usable_char_count
from app.services.indexing_bridge import build_search_document, build_synthetic_text
from app.services.llm_client import get_llm_client
from app.services.skill_resolver import CatalogValidationError, enrich_profile
from app.services.ocr_service import ocr_pdf_pages
from app.services.search_client import get_ingest_search_client, get_search_client
from app.tasks.ingestion import start_cv_ingestion
from app.utils.file_validation import validate_and_persist_upload
from app.utils.language_detect import detect_language
from app.utils.metrics import cv_unprocessable_total

router = APIRouter()

ProfileStatus = Literal["pending", "extracting", "indexing", "ready", "failed", "index_failed"]


def _narrow_profile_status(status: str) -> ProfileStatus:
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


def _cv_to_profile_response(cv: CVProfile) -> CVProfileResponse:
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


def _build_status_response(cv: CVProfile, job: CVProcessingJob | None) -> CVStatusResponse:
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


async def _delete_cv_and_index(
    *,
    db: AsyncSession,
    cv_service: CVService,
    cv: CVProfile,
) -> None:
    external_id = cv.search_doc_external_id or cv.file_hash
    client = get_ingest_search_client()
    try:
        await client.delete_document_if_exists(
            collection_id=cv.collection_id,
            external_id=external_id,
        )
    finally:
        await client.aclose()
    await cv_service.delete_cv(db=db, cv_id=cv.cv_id)


async def _replace_cv_file(
    *,
    db: AsyncSession,
    cv_service: CVService,
    cv: CVProfile,
    file: UploadFile,
    callback_url: str | None,
    response: Response,
) -> CVUploadResponse:
    path, new_hash = await validate_and_persist_upload(file)

    if new_hash == cv.file_hash:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        latest_job = await cv_service.get_latest_processing_job(db=db, cv_id=cv.cv_id)
        response.status_code = 200
        return CVUploadResponse(
            cv_id=cv.cv_id,
            job_id=latest_job.job_id if latest_job else cv.cv_id,
            status=_narrow_profile_status(cv.status),
            file_hash=cv.file_hash,
            no_change=True,
        )

    await cv_service.check_file_hash_conflict(
        db=db,
        collection_id=cv.collection_id,
        file_hash=new_hash,
        exclude_cv_id=cv.cv_id,
    )

    if callback_url is not None:
        cv.callback_url = callback_url

    cv, job = await cv_service.reset_cv_for_reingest(
        db=db,
        cv=cv,
        new_file_hash=new_hash,
    )

    start_cv_ingestion(
        cv_id=cv.cv_id,
        job_id=job.job_id,
        collection_id=cv.collection_id,
        file_hash=new_hash,
        file_path=str(path),
        mime=file.content_type or "",
    )

    response.status_code = 202
    return CVUploadResponse(
        cv_id=cv.cv_id,
        job_id=job.job_id,
        status="pending",
        file_hash=new_hash,
        no_change=False,
    )


def _employee_email(profile: CandidateProfile) -> str | None:
    return profile.employee.email if profile.employee else None


async def _apply_profile_patch(
    *,
    db: AsyncSession,
    cv_service: CVService,
    cv: CVProfile,
    patch: CandidateProfilePatch,
) -> CVProfileResponse:
    if cv.status not in ("ready", "index_failed") or cv.profile_data is None:
        raise HTTPException(
            status_code=409,
            detail={
                "detail": (
                    "CV must be fully ingested before its profile can be "
                    f"patched (current status: {cv.status})"
                ),
                "code": "CV_NOT_READY",
            },
        )

    patch_dict = patch.model_dump(mode="json", exclude_unset=True)
    merged_dict = dict(cv.profile_data)
    merged_dict.update(patch_dict)
    merged = CandidateProfile.model_validate(merged_dict)

    try:
        enrich_profile(merged, catalog_store, strict=True)
    except CatalogValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"detail": str(exc), "code": "INVALID_CATALOG_VALUE"},
        ) from exc

    email = _employee_email(merged)
    old_email = cv.email
    if email and email != old_email:
        await cv_service.check_email_conflict(
            db=db,
            collection_id=cv.collection_id,
            email=email,
            exclude_cv_id=cv.cv_id,
        )

    # For JSON-created candidates the indexed content is a synthetic projection
    # of the profile, so it must be regenerated from the merged profile —
    # otherwise the embedding stays frozen at create-time and the patch never
    # reaches Semantic Search. File-based CVs keep their real extracted text.
    new_raw_text = cv.raw_text or ""
    if cv.extraction_method == "json_input":
        new_raw_text = build_synthetic_text(merged)

    cv = await cv_service.update_profile_data(
        db=db,
        cv=cv,
        merged_profile=merged,
        raw_text=new_raw_text,
    )

    doc = build_search_document(
        external_id=cv.external_id,
        profile=merged,
        raw_text=new_raw_text,
        language=cv.language,
    )
    client = get_ingest_search_client()
    try:
        try:
            await client.ingest_documents(
                collection_id=cv.collection_id,
                documents=[
                    {
                        "external_id": doc.external_id,
                        "content": doc.content,
                        "metadata": doc.metadata,
                    }
                ],
                upsert=True,
            )
        except Exception as exc:
            await cv_service.mark_index_failed(db=db, cv=cv)
            raise HTTPException(
                status_code=502,
                detail={
                    "detail": f"Semantic Search ingest failed: {exc}",
                    "code": "UPSTREAM_SEARCH_ERROR",
                },
            ) from exc
    finally:
        await client.aclose()

    return _cv_to_profile_response(cv)


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


@router.post("/candidates/extract", response_model=CVExtractionResponse)
async def extract_cv(
    file: UploadFile = File(...),
    _: str = Depends(get_api_key),
) -> CVExtractionResponse:
    """Stateless CV extraction for the preview-edit-confirm flow."""
    path, file_hash = await validate_and_persist_upload(file)
    mime = file.content_type or ""

    try:
        processor = DocumentProcessor()
        extracted = await processor.extract(path, mime)
        raw_text = extracted.text
        extraction_method = extracted.method

        if extracted.needs_ocr and mime == "application/pdf":
            settings = get_settings()
            text, method = await asyncio.to_thread(
                ocr_pdf_pages, path, dpi=settings.ocr_dpi, min_chars=50
            )
            raw_text = text
            extraction_method = method

        settings = get_settings()
        if usable_char_count(raw_text) < settings.min_cv_text_chars:
            cv_unprocessable_total.inc()
            raise HTTPException(
                status_code=422,
                detail={
                    "detail": "CV could not be processed: no readable text found.",
                    "code": "UNPROCESSABLE_CV",
                },
            )

        language = await detect_language(raw_text)

        extraction_notes = (
            "Text extracted via OCR — may contain artifacts"
            if "ocr" in extraction_method
            else "Clean text extraction from document"
        )
        try:
            llm = get_llm_client()
            extractor = EntityExtractor(llm)
            profile = await extractor.extract(
                cv_text=raw_text,
                detected_language=language,
                extraction_notes=extraction_notes,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "detail": f"LLM entity extraction failed: {exc}",
                    "code": "UPSTREAM_LLM_ERROR",
                },
            ) from exc

        enrich_profile(profile, catalog_store, strict=False)

        return CVExtractionResponse(
            profile=profile,
            language=language,
            extraction_method=extraction_method,
            file_hash=file_hash,
            raw_text=raw_text,
        )
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


@router.post("/candidates", response_model=CVProfileResponse)
async def create_cv_from_json(
    req: CandidateCreateRequest,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVProfileResponse:
    """Create a candidate profile from structured JSON (no CV document)."""
    profile = req.profile
    try:
        enrich_profile(profile, catalog_store, strict=True)
    except CatalogValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"detail": str(exc), "code": "INVALID_CATALOG_VALUE"},
        ) from exc

    synthetic_text = build_synthetic_text(profile)
    file_hash = hashlib.sha256(synthetic_text.encode()).hexdigest()
    lang = await detect_language(synthetic_text)

    cv, _job = await cv_service.create_cv_for_indexing(
        db=db,
        collection_id=req.collection_id,
        external_id=req.external_id,
        file_hash=file_hash,
        profile=profile,
        raw_text=synthetic_text,
        language=lang,
        callback_url=req.callback_url,
    )

    doc = build_search_document(
        external_id=cv.external_id,
        profile=profile,
        raw_text=synthetic_text,
        language=lang,
    )
    client = get_ingest_search_client()
    try:
        try:
            result = await client.ingest_documents(
                collection_id=req.collection_id,
                documents=[
                    {
                        "external_id": doc.external_id,
                        "content": doc.content,
                        "metadata": doc.metadata,
                    }
                ],
                upsert=True,
            )
        except Exception as exc:
            await cv_service.mark_index_failed(db=db, cv=cv)
            raise HTTPException(
                status_code=502,
                detail={
                    "detail": f"Semantic Search ingest failed: {exc}",
                    "code": "UPSTREAM_SEARCH_ERROR",
                },
            ) from exc
    finally:
        await client.aclose()

    ingest_job_id = result.get("job_id")
    cv.search_ingest_job_id = str(ingest_job_id) if ingest_job_id else None
    await db.commit()
    await db.refresh(cv)

    return _cv_to_profile_response(cv)


@router.get("/candidates/{cv_id}", response_model=CVProfileResponse)
async def get_cv(
    cv_id: uuid.UUID,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVProfileResponse:
    cv = await cv_service.get_cv(db=db, cv_id=cv_id)
    return _cv_to_profile_response(cv)


@router.get("/candidates/{cv_id}/status", response_model=CVStatusResponse)
async def get_cv_status(
    cv_id: uuid.UUID,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVStatusResponse:
    cv = await cv_service.get_cv(db=db, cv_id=cv_id)
    job = await cv_service.get_latest_processing_job(db=db, cv_id=cv_id)
    return _build_status_response(cv, job)


@router.delete("/candidates/{cv_id}", status_code=204)
async def delete_cv(
    cv_id: uuid.UUID,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> None:
    cv = await cv_service.get_cv(db=db, cv_id=cv_id)
    await _delete_cv_and_index(db=db, cv_service=cv_service, cv=cv)
    return None


@router.put("/candidates/{cv_id}", status_code=202, response_model=CVUploadResponse)
async def put_cv(
    cv_id: uuid.UUID,
    response: Response,
    file: UploadFile = File(...),
    callback_url: str | None = Form(default=None),
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVUploadResponse:
    cv = await cv_service.get_cv(db=db, cv_id=cv_id)
    return await _replace_cv_file(
        db=db,
        cv_service=cv_service,
        cv=cv,
        file=file,
        callback_url=callback_url,
        response=response,
    )


@router.patch("/candidates/{cv_id}", response_model=CVProfileResponse)
async def patch_cv(
    cv_id: uuid.UUID,
    patch: CandidateProfilePatch,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVProfileResponse:
    cv = await cv_service.get_cv(db=db, cv_id=cv_id)
    return await _apply_profile_patch(
        db=db,
        cv_service=cv_service,
        cv=cv,
        patch=patch,
    )


# ---------------------------------------------------------------------------
# External-id routes
# ---------------------------------------------------------------------------


@router.get(
    "/collections/{collection_id}/candidates/{external_id}",
    response_model=CVProfileResponse,
)
async def get_cv_by_external_id(
    collection_id: uuid.UUID,
    external_id: str,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVProfileResponse:
    cv = await cv_service.get_cv_by_external_id(
        db=db, collection_id=collection_id, external_id=external_id
    )
    return _cv_to_profile_response(cv)


@router.get(
    "/collections/{collection_id}/candidates/{external_id}/status",
    response_model=CVStatusResponse,
)
async def get_cv_status_by_external_id(
    collection_id: uuid.UUID,
    external_id: str,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVStatusResponse:
    cv = await cv_service.get_cv_by_external_id(
        db=db, collection_id=collection_id, external_id=external_id
    )
    job = await cv_service.get_latest_processing_job(db=db, cv_id=cv.cv_id)
    return _build_status_response(cv, job)


@router.delete(
    "/collections/{collection_id}/candidates/{external_id}",
    status_code=204,
)
async def delete_cv_by_external_id(
    collection_id: uuid.UUID,
    external_id: str,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> None:
    cv = await cv_service.get_cv_by_external_id(
        db=db, collection_id=collection_id, external_id=external_id
    )
    await _delete_cv_and_index(db=db, cv_service=cv_service, cv=cv)
    return None


@router.put(
    "/collections/{collection_id}/candidates/{external_id}",
    status_code=202,
    response_model=CVUploadResponse,
)
async def put_cv_by_external_id(
    collection_id: uuid.UUID,
    external_id: str,
    response: Response,
    file: UploadFile = File(...),
    callback_url: str | None = Form(default=None),
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVUploadResponse:
    cv = await cv_service.get_cv_by_external_id(
        db=db, collection_id=collection_id, external_id=external_id
    )
    return await _replace_cv_file(
        db=db,
        cv_service=cv_service,
        cv=cv,
        file=file,
        callback_url=callback_url,
        response=response,
    )


@router.patch(
    "/collections/{collection_id}/candidates/{external_id}",
    response_model=CVProfileResponse,
)
async def patch_cv_by_external_id(
    collection_id: uuid.UUID,
    external_id: str,
    patch: CandidateProfilePatch,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    cv_service: CVService = Depends(get_cv_service),
) -> CVProfileResponse:
    cv = await cv_service.get_cv_by_external_id(
        db=db, collection_id=collection_id, external_id=external_id
    )
    return await _apply_profile_patch(
        db=db,
        cv_service=cv_service,
        cv=cv,
        patch=patch,
    )


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
