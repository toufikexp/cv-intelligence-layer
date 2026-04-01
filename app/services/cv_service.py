from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.db import CVProcessingJob, CVProfile


class CVService:
    async def create_pending_cv(
        self,
        *,
        db: AsyncSession,
        collection_id: uuid.UUID,
        external_id: str | None,
        file_hash: str,
    ) -> tuple[CVProfile, CVProcessingJob]:
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

