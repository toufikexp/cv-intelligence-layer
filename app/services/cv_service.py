from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import CVProcessingJob, CVProfile


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

    async def get_cv(self, *, db: AsyncSession, cv_id: uuid.UUID) -> CVProfile:
        res = await db.execute(select(CVProfile).where(CVProfile.cv_id == cv_id))
        cv = res.scalar_one_or_none()
        if not cv:
            raise HTTPException(status_code=404, detail={"detail": "CV not found", "code": "NOT_FOUND"})
        return cv

    async def delete_cv(self, *, db: AsyncSession, cv_id: uuid.UUID) -> CVProfile:
        cv = await self.get_cv(db=db, cv_id=cv_id)
        await db.delete(cv)
        await db.commit()
        return cv

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

