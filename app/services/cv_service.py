from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import CVProcessingJob, CVProfile
from app.models.schemas import CandidateProfile


class CVService:
    async def create_pending_cv(
        self,
        *,
        db: AsyncSession,
        collection_id: uuid.UUID,
        external_id: str,
        file_hash: str,
        callback_url: str | None = None,
    ) -> tuple[CVProfile, CVProcessingJob]:
        # Reject reuse of external_id within a collection first — it's the
        # caller-owned business key and should collide loudly before we even
        # consider file-level deduplication.
        existing_ext = await db.execute(
            select(CVProfile).where(
                CVProfile.collection_id == collection_id,
                CVProfile.external_id == external_id,
            )
        )
        if existing_ext.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": f"external_id '{external_id}' already exists in this collection",
                    "code": "DUPLICATE_EXTERNAL_ID",
                },
            )

        existing = await db.execute(
            select(CVProfile).where(CVProfile.collection_id == collection_id, CVProfile.file_hash == file_hash)
        )
        found = existing.scalar_one_or_none()
        if found:
            raise HTTPException(
                status_code=409,
                detail={"detail": str(found.cv_id), "code": "DUPLICATE_FILE"},
            )

        cv = CVProfile(
            cv_id=uuid.uuid4(),
            external_id=external_id,
            collection_id=collection_id,
            file_hash=file_hash,
            callback_url=callback_url,
            status="pending",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        job = CVProcessingJob(
            job_id=uuid.uuid4(),
            cv_id=cv.cv_id,
            stage="validate_file",
            status="pending",
            progress_pct=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(cv)
        db.add(job)
        await db.commit()
        await db.refresh(cv)
        await db.refresh(job)
        return cv, job

    async def create_cv_for_indexing(
        self,
        *,
        db: AsyncSession,
        collection_id: uuid.UUID,
        external_id: str,
        file_hash: str,
        profile: CandidateProfile,
        raw_text: str,
        language: str | None,
        callback_url: str | None = None,
    ) -> tuple[CVProfile, CVProcessingJob]:
        """Create a CV row from structured JSON (no document upload).

        The row is born ``indexing`` — the caller must submit the document
        to Semantic Search and save the ``search_ingest_job_id``.  The
        ingestion webhook flips the status to ``ready`` once embedding
        completes, exactly like the upload/Celery path.
        """
        existing_ext = await db.execute(
            select(CVProfile).where(
                CVProfile.collection_id == collection_id,
                CVProfile.external_id == external_id,
            )
        )
        if existing_ext.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": f"external_id '{external_id}' already exists in this collection",
                    "code": "DUPLICATE_EXTERNAL_ID",
                },
            )

        existing = await db.execute(
            select(CVProfile).where(CVProfile.collection_id == collection_id, CVProfile.file_hash == file_hash)
        )
        found = existing.scalar_one_or_none()
        if found:
            raise HTTPException(
                status_code=409,
                detail={"detail": str(found.cv_id), "code": "DUPLICATE_FILE"},
            )

        now = datetime.utcnow()
        cv = CVProfile(
            cv_id=uuid.uuid4(),
            external_id=external_id,
            collection_id=collection_id,
            file_hash=file_hash,
            callback_url=callback_url,
            status="indexing",
            profile_data=profile.model_dump(mode="json"),
            raw_text=raw_text,
            language=language,
            extraction_method="json_input",
            candidate_name=profile.name,
            email=profile.email,
            phone=profile.phone,
            search_doc_external_id=external_id,
            created_at=now,
            updated_at=now,
        )
        job = CVProcessingJob(
            job_id=uuid.uuid4(),
            cv_id=cv.cv_id,
            stage="indexing",
            status="submitted",
            progress_pct=90,
            created_at=now,
            updated_at=now,
        )
        db.add(cv)
        db.add(job)
        await db.commit()
        await db.refresh(cv)
        await db.refresh(job)
        return cv, job

    async def get_cv(self, *, db: AsyncSession, cv_id: uuid.UUID) -> CVProfile:
        res = await db.execute(select(CVProfile).where(CVProfile.cv_id == cv_id))
        cv = res.scalar_one_or_none()
        if not cv:
            raise HTTPException(status_code=404, detail={"detail": "CV not found", "code": "NOT_FOUND"})
        return cv

    async def get_cv_by_external_id(
        self,
        *,
        db: AsyncSession,
        collection_id: uuid.UUID,
        external_id: str,
    ) -> CVProfile:
        """Look up a CV by the caller-supplied business key.

        `external_id` is only unique within a collection, so both values are
        required. Mirrors `get_cv` semantics: raises 404 when not found.
        """
        res = await db.execute(
            select(CVProfile).where(
                CVProfile.collection_id == collection_id,
                CVProfile.external_id == external_id,
            )
        )
        cv = res.scalar_one_or_none()
        if not cv:
            raise HTTPException(status_code=404, detail={"detail": "CV not found", "code": "NOT_FOUND"})
        return cv

    async def delete_cv(self, *, db: AsyncSession, cv_id: uuid.UUID) -> CVProfile:
        cv = await self.get_cv(db=db, cv_id=cv_id)
        await db.delete(cv)
        await db.commit()
        return cv

    async def check_file_hash_conflict(
        self,
        *,
        db: AsyncSession,
        collection_id: uuid.UUID,
        file_hash: str,
        exclude_cv_id: uuid.UUID,
    ) -> None:
        """Raise 409 DUPLICATE_FILE if another CV in the collection has this hash.

        Used by the re-upload (PUT) path before touching the row. The
        ``uq_cv_profiles_collection_file_hash`` unique constraint would catch
        the collision at commit time anyway, but failing loudly here lets us
        return a well-formed error with the conflicting ``cv_id``.
        """
        res = await db.execute(
            select(CVProfile).where(
                CVProfile.collection_id == collection_id,
                CVProfile.file_hash == file_hash,
                CVProfile.cv_id != exclude_cv_id,
            )
        )
        found = res.scalar_one_or_none()
        if found:
            raise HTTPException(
                status_code=409,
                detail={"detail": str(found.cv_id), "code": "DUPLICATE_FILE"},
            )

    async def reset_cv_for_reingest(
        self,
        *,
        db: AsyncSession,
        cv: CVProfile,
        new_file_hash: str,
    ) -> tuple[CVProfile, CVProcessingJob]:
        """Prepare an existing CV row for a fresh ingestion run (PUT /upload).

        Preserves identity (``cv_id``, ``external_id``, ``collection_id``,
        ``created_at``, ``callback_url``, ``search_doc_external_id``) and
        wipes every field that the ingestion pipeline repopulates. Creates a
        new ``CVProcessingJob`` so the re-run has its own status track.
        """
        now = datetime.utcnow()
        cv.file_hash = new_file_hash
        cv.status = "pending"
        cv.profile_data = None
        cv.raw_text = None
        cv.language = None
        cv.extraction_method = None
        cv.candidate_name = None
        cv.email = None
        cv.phone = None
        cv.search_ingest_job_id = None
        cv.updated_at = now

        job = CVProcessingJob(
            job_id=uuid.uuid4(),
            cv_id=cv.cv_id,
            stage="validate_file",
            status="pending",
            progress_pct=0,
            created_at=now,
            updated_at=now,
        )
        db.add(job)
        await db.commit()
        await db.refresh(cv)
        await db.refresh(job)
        return cv, job

    async def update_profile_data(
        self,
        *,
        db: AsyncSession,
        cv: CVProfile,
        merged_profile: CandidateProfile,
    ) -> CVProfile:
        """Write a merged CandidateProfile back to the CV row (PATCH path).

        The caller is responsible for merging the patch into the existing
        ``profile_data`` and for checking unique-constraint conflicts (e.g.
        email) before invoking this. This method only handles the write:
        ``profile_data`` plus denormalized ``candidate_name`` / ``email`` /
        ``phone`` columns, and the ``updated_at`` bump.
        """
        cv.profile_data = merged_profile.model_dump(mode="json")
        cv.candidate_name = merged_profile.name
        cv.email = merged_profile.email
        cv.phone = merged_profile.phone
        cv.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(cv)
        return cv

    async def check_email_conflict(
        self,
        *,
        db: AsyncSession,
        collection_id: uuid.UUID,
        email: str,
        exclude_cv_id: uuid.UUID,
    ) -> None:
        """Raise 409 DUPLICATE_EMAIL if another CV in the collection has this email."""
        res = await db.execute(
            select(CVProfile).where(
                CVProfile.collection_id == collection_id,
                CVProfile.email == email,
                CVProfile.cv_id != exclude_cv_id,
            )
        )
        if res.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": f"email '{email}' already exists in this collection",
                    "code": "DUPLICATE_EMAIL",
                },
            )

    async def mark_index_failed(self, *, db: AsyncSession, cv: CVProfile) -> None:
        """Set the CV status to ``index_failed`` after a synchronous re-index error."""
        cv.status = "index_failed"
        cv.updated_at = datetime.utcnow()
        await db.commit()

    async def get_latest_processing_job(
        self,
        *,
        db: AsyncSession,
        cv_id: uuid.UUID,
    ) -> CVProcessingJob | None:
        """Return the most recent processing job for a CV."""
        res = await db.execute(
            select(CVProcessingJob)
            .where(CVProcessingJob.cv_id == cv_id)
            .order_by(CVProcessingJob.created_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()


def get_cv_service() -> CVService:
    return CVService()

