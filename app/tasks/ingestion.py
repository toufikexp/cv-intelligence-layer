from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from celery import chain
from celery.utils.log import get_task_logger
from sqlalchemy import select, update

from app.models.database import SessionLocal
from app.models.db import CVProcessingJob, CVProfile
from app.services.document_processor import DocumentProcessor
from app.services.entity_extractor import EntityExtractor
from app.services.indexing_bridge import build_search_document
from app.services.llm_client import get_llm_client
from app.services.ocr_service import ocr_pdf_pages
from app.services.search_client import get_ingest_search_client
from app.tasks.celery_app import celery_app
from app.utils.language_detect import detect_language

logger = get_task_logger(__name__)


async def _update_job(job_id: uuid.UUID, **fields: Any) -> None:
    async with SessionLocal() as db:
        await db.execute(update(CVProcessingJob).where(CVProcessingJob.job_id == job_id).values(**fields))
        await db.commit()


async def _update_cv(cv_id: uuid.UUID, **fields: Any) -> None:
    async with SessionLocal() as db:
        await db.execute(update(CVProfile).where(CVProfile.cv_id == cv_id).values(**fields))
        await db.commit()


async def _get_cv(cv_id: uuid.UUID) -> CVProfile | None:
    async with SessionLocal() as db:
        res = await db.execute(select(CVProfile).where(CVProfile.cv_id == cv_id))
        return res.scalar_one_or_none()


def start_cv_ingestion(
    *,
    cv_id: uuid.UUID,
    job_id: uuid.UUID,
    collection_id: uuid.UUID,
    file_hash: str,
    file_path: str,
    mime: str,
) -> None:
    chain(
        validate_file.s(str(cv_id), str(job_id), str(collection_id), file_hash, file_path, mime),
        extract_text.s(),
        ocr_if_needed.s(),
        detect_lang.s(),
        extract_entities.s(),
        index_in_search.s(),
        finalize_status.s(),
    ).apply_async()


@celery_app.task(bind=True, max_retries=3)
def validate_file(
    self,
    cv_id: str,
    job_id: str,
    collection_id: str,
    file_hash: str,
    file_path: str,
    mime: str,
) -> dict[str, Any]:
    logger.info("stage=validate_file status=started cv_id=%s job_id=%s", cv_id, job_id)
    p = Path(file_path)
    if not p.exists():
        raise ValueError("Uploaded file missing on disk")
    asyncio.run(
        _update_cv(
            uuid.UUID(cv_id),
            status="extracting",
            updated_at=datetime.utcnow(),
        )
    )
    asyncio.run(
        _update_job(
            uuid.UUID(job_id),
            stage="validate_file",
            status="running",
            progress_pct=5,
            updated_at=datetime.utcnow(),
        )
    )
    return {
        "cv_id": cv_id,
        "job_id": job_id,
        "collection_id": collection_id,
        "file_hash": file_hash,
        "file_path": file_path,
        "mime": mime,
    }


@celery_app.task(bind=True, max_retries=3)
def extract_text(self, payload: dict[str, Any]) -> dict[str, Any]:
    cv_id = uuid.UUID(payload["cv_id"])
    job_id = uuid.UUID(payload["job_id"])
    logger.info("stage=extract_text status=started cv_id=%s job_id=%s", cv_id, job_id)

    cv = asyncio.run(_get_cv(cv_id))
    if not cv or cv.status not in {"pending", "extracting"}:
        return payload

    processor = DocumentProcessor()
    extracted = asyncio.run(processor.extract(Path(payload["file_path"]), payload["mime"]))
    payload["raw_text"] = extracted.text
    payload["extraction_method"] = extracted.method
    payload["needs_ocr"] = extracted.needs_ocr

    asyncio.run(
        _update_job(
            job_id,
            stage="extract_text",
            status="completed",
            progress_pct=25,
            updated_at=datetime.utcnow(),
        )
    )
    return payload


@celery_app.task(bind=True, max_retries=3)
def ocr_if_needed(self, payload: dict[str, Any]) -> dict[str, Any]:
    cv_id = uuid.UUID(payload["cv_id"])
    job_id = uuid.UUID(payload["job_id"])
    if not payload.get("needs_ocr") or payload.get("mime") != "application/pdf":
        return payload

    logger.info("stage=ocr status=started cv_id=%s job_id=%s", cv_id, job_id)
    asyncio.run(
        _update_cv(cv_id, status="ocr_processing", updated_at=datetime.utcnow())
    )
    asyncio.run(
        _update_job(
            job_id,
            stage="ocr",
            status="running",
            progress_pct=35,
            updated_at=datetime.utcnow(),
        )
    )

    from app.config import get_settings

    settings = get_settings()
    text, method = ocr_pdf_pages(
        Path(payload["file_path"]),
        dpi=settings.ocr_dpi,
        min_chars=50,
    )
    payload["raw_text"] = text
    payload["extraction_method"] = method

    asyncio.run(
        _update_job(
            job_id,
            stage="ocr",
            status="completed",
            progress_pct=45,
            updated_at=datetime.utcnow(),
        )
    )
    asyncio.run(
        _update_cv(cv_id, status="extracting", updated_at=datetime.utcnow())
    )
    return payload


@celery_app.task(bind=True, max_retries=3)
def detect_lang(self, payload: dict[str, Any]) -> dict[str, Any]:
    cv_id = uuid.UUID(payload["cv_id"])
    job_id = uuid.UUID(payload["job_id"])
    logger.info("stage=detect_language status=started cv_id=%s job_id=%s", cv_id, job_id)
    lang = asyncio.run(detect_language(payload.get("raw_text", "")))
    payload["language"] = lang
    asyncio.run(
        _update_job(
            job_id,
            stage="detect_language",
            status="completed",
            progress_pct=55,
            updated_at=datetime.utcnow(),
        )
    )
    return payload


@celery_app.task(bind=True, max_retries=3)
def extract_entities(self, payload: dict[str, Any]) -> dict[str, Any]:
    cv_id = uuid.UUID(payload["cv_id"])
    job_id = uuid.UUID(payload["job_id"])
    logger.info("stage=entity_extraction status=started cv_id=%s job_id=%s", cv_id, job_id)
    asyncio.run(
        _update_cv(cv_id, status="entity_extraction", updated_at=datetime.utcnow())
    )
    asyncio.run(
        _update_job(
            job_id,
            stage="entity_extraction",
            status="running",
            progress_pct=60,
            updated_at=datetime.utcnow(),
        )
    )

    extraction_method = str(payload.get("extraction_method") or "text_extraction")
    extraction_notes = (
        "Text extracted via OCR — may contain artifacts"
        if "ocr" in extraction_method
        else "Clean text extraction from document"
    )

    llm = get_llm_client()
    extractor = EntityExtractor(llm)
    profile = asyncio.run(
        extractor.extract(
            cv_text=payload.get("raw_text", ""),
            detected_language=payload.get("language", "mixed"),
            extraction_notes=extraction_notes,
        )
    )
    payload["profile"] = profile.model_dump(mode="json")
    asyncio.run(
        _update_job(
            job_id,
            stage="entity_extraction",
            status="completed",
            progress_pct=75,
            updated_at=datetime.utcnow(),
        )
    )
    return payload


@celery_app.task(bind=True, max_retries=3)
def index_in_search(self, payload: dict[str, Any]) -> dict[str, Any]:
    cv_id = uuid.UUID(payload["cv_id"])
    job_id = uuid.UUID(payload["job_id"])
    logger.info("stage=indexing status=started cv_id=%s job_id=%s", cv_id, job_id)

    asyncio.run(
        _update_cv(cv_id, status="indexing", updated_at=datetime.utcnow())
    )
    asyncio.run(
        _update_job(
            job_id,
            stage="indexing",
            status="running",
            progress_pct=80,
            updated_at=datetime.utcnow(),
        )
    )

    client = get_ingest_search_client()
    try:
        from app.models.schemas import CandidateProfile

        profile = CandidateProfile.model_validate(payload["profile"], strict=False)
        doc = build_search_document(
            file_hash=str(payload.get("file_hash", cv_id)),
            profile=profile,
            language=payload.get("language"),
        )
        result = asyncio.run(
            client.ingest_documents(
                collection_id=uuid.UUID(payload["collection_id"]),
                documents=[
                    {
                        "external_id": doc.external_id,
                        "content": doc.content,
                        "metadata": doc.metadata,
                    }
                ],
                upsert=True,
            )
        )
        payload["search_result"] = result
    finally:
        asyncio.run(client.aclose())

    asyncio.run(
        _update_job(
            job_id,
            stage="indexing",
            status="completed",
            progress_pct=90,
            updated_at=datetime.utcnow(),
        )
    )
    return payload


@celery_app.task(bind=True, max_retries=3)
def finalize_status(self, payload: dict[str, Any]) -> dict[str, Any]:
    cv_id = uuid.UUID(payload["cv_id"])
    job_id = uuid.UUID(payload["job_id"])
    logger.info("stage=finalize status=started cv_id=%s job_id=%s", cv_id, job_id)

    async def _final() -> None:
        async with SessionLocal() as db:
            await db.execute(
                update(CVProfile)
                .where(CVProfile.cv_id == cv_id)
                .values(
                    raw_text=payload.get("raw_text"),
                    profile_data=payload.get("profile"),
                    candidate_name=(payload.get("profile", {}) or {}).get("name"),
                    email=(payload.get("profile", {}) or {}).get("email"),
                    phone=(payload.get("profile", {}) or {}).get("phone"),
                    language=payload.get("language"),
                    extraction_method=payload.get("extraction_method"),
                    search_doc_external_id=str(payload.get("file_hash") or payload.get("cv_id")),
                    status="ready",
                    updated_at=datetime.utcnow(),
                )
            )
            await db.execute(
                update(CVProcessingJob)
                .where(CVProcessingJob.job_id == job_id)
                .values(
                    status="completed",
                    progress_pct=100,
                    completed_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            await db.commit()

    asyncio.run(_final())
    return payload
