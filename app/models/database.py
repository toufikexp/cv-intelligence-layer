from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class CVProfile(Base):
    __tablename__ = "cv_profiles"

    cv_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    collection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    candidate_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    profile_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    language: Mapped[str | None] = mapped_column(String(5), nullable=True, index=True)
    extraction_method: Mapped[str | None] = mapped_column(String(20), nullable=True)

    search_doc_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    processing_jobs: Mapped[list["CVProcessingJob"]] = relationship(back_populates="cv", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("collection_id", "file_hash", name="uq_cv_profiles_collection_file_hash"),
        UniqueConstraint("collection_id", "email", name="uq_cv_profiles_collection_email"),
        Index("ix_cv_profiles_profile_data_gin", "profile_data", postgresql_using="gin"),
    )


class CVProcessingJob(Base):
    __tablename__ = "cv_processing_jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    cv_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cv_profiles.cv_id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_pct: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cv: Mapped[CVProfile] = relationship(back_populates="processing_jobs")


class CVJob(Base):
    __tablename__ = "cv_jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    collection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    preferred_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)


class CVRankingResult(Base):
    __tablename__ = "cv_ranking_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    cv_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    composite_score: Mapped[float] = mapped_column(nullable=False)
    llm_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    ranked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("job_id", "cv_id", name="uq_cv_ranking_results_job_cv"),
    )


class CVAnswerSession(Base):
    __tablename__ = "cv_answer_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    cv_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    total_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    max_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------

def create_engine() -> AsyncEngine:
    """Create the async SQLAlchemy engine."""
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


engine = create_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency providing an async DB session."""
    async with SessionLocal() as session:
        yield session
