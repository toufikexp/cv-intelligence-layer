"""init

Revision ID: 0001_init
Revises: 
Create Date: 2026-04-01

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cv_profiles",
        sa.Column("cv_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("profile_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=5), nullable=True),
        sa.Column("extraction_method", sa.String(length=20), nullable=True),
        sa.Column("search_doc_external_id", sa.String(length=255), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("collection_id", "email", name="uq_cv_profiles_collection_email"),
        sa.UniqueConstraint("collection_id", "file_hash", name="uq_cv_profiles_collection_file_hash"),
    )
    op.create_index("ix_cv_profiles_collection_id", "cv_profiles", ["collection_id"])
    op.create_index("ix_cv_profiles_candidate_name", "cv_profiles", ["candidate_name"])
    op.create_index("ix_cv_profiles_search_doc_external_id", "cv_profiles", ["search_doc_external_id"])
    op.create_index("ix_cv_profiles_file_hash", "cv_profiles", ["file_hash"])
    op.create_index("ix_cv_profiles_status", "cv_profiles", ["status"])
    op.create_index("ix_cv_profiles_created_at", "cv_profiles", ["created_at"])
    op.create_index("ix_cv_profiles_language", "cv_profiles", ["language"])
    op.create_index(
        "ix_cv_profiles_profile_data_gin",
        "cv_profiles",
        ["profile_data"],
        postgresql_using="gin",
    )

    op.create_table(
        "cv_processing_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("cv_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cv_profiles.cv_id", ondelete="CASCADE")),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("progress_pct", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_cv_processing_jobs_cv_id", "cv_processing_jobs", ["cv_id"])
    op.create_index("ix_cv_processing_jobs_status", "cv_processing_jobs", ["status"])
    op.create_index("ix_cv_processing_jobs_created_at", "cv_processing_jobs", ["created_at"])

    op.create_table(
        "cv_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("required_skills", sa.JSON(), nullable=False),
        sa.Column("preferred_skills", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cv_jobs_collection_id", "cv_jobs", ["collection_id"])
    op.create_index("ix_cv_jobs_created_at", "cv_jobs", ["created_at"])

    op.create_table(
        "cv_ranking_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cv_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("composite_score", sa.Float(), nullable=False),
        sa.Column("llm_reasoning", sa.Text(), nullable=True),
        sa.Column("ranked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "cv_id", name="uq_cv_ranking_results_job_cv"),
    )
    op.create_index("ix_cv_ranking_results_job_id", "cv_ranking_results", ["job_id"])
    op.create_index("ix_cv_ranking_results_cv_id", "cv_ranking_results", ["cv_id"])
    op.create_index("ix_cv_ranking_results_ranked_at", "cv_ranking_results", ["ranked_at"])

    op.create_table(
        "cv_answer_sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("cv_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cv_answer_sessions_cv_id", "cv_answer_sessions", ["cv_id"])
    op.create_index("ix_cv_answer_sessions_created_at", "cv_answer_sessions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_cv_answer_sessions_created_at", table_name="cv_answer_sessions")
    op.drop_index("ix_cv_answer_sessions_cv_id", table_name="cv_answer_sessions")
    op.drop_table("cv_answer_sessions")

    op.drop_index("ix_cv_ranking_results_ranked_at", table_name="cv_ranking_results")
    op.drop_index("ix_cv_ranking_results_cv_id", table_name="cv_ranking_results")
    op.drop_index("ix_cv_ranking_results_job_id", table_name="cv_ranking_results")
    op.drop_table("cv_ranking_results")

    op.drop_index("ix_cv_jobs_created_at", table_name="cv_jobs")
    op.drop_index("ix_cv_jobs_collection_id", table_name="cv_jobs")
    op.drop_table("cv_jobs")

    op.drop_index("ix_cv_processing_jobs_created_at", table_name="cv_processing_jobs")
    op.drop_index("ix_cv_processing_jobs_status", table_name="cv_processing_jobs")
    op.drop_index("ix_cv_processing_jobs_cv_id", table_name="cv_processing_jobs")
    op.drop_table("cv_processing_jobs")

    op.drop_index("ix_cv_profiles_profile_data_gin", table_name="cv_profiles")
    op.drop_index("ix_cv_profiles_language", table_name="cv_profiles")
    op.drop_index("ix_cv_profiles_created_at", table_name="cv_profiles")
    op.drop_index("ix_cv_profiles_status", table_name="cv_profiles")
    op.drop_index("ix_cv_profiles_file_hash", table_name="cv_profiles")
    op.drop_index("ix_cv_profiles_search_doc_external_id", table_name="cv_profiles")
    op.drop_index("ix_cv_profiles_candidate_name", table_name="cv_profiles")
    op.drop_index("ix_cv_profiles_collection_id", table_name="cv_profiles")
    op.drop_table("cv_profiles")

