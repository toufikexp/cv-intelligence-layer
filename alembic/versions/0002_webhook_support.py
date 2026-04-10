"""Add webhook support columns to cv_profiles

Revision ID: 0002_webhook_support
Revises: 0001_init
Create Date: 2026-04-10

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_webhook_support"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cv_profiles", sa.Column("callback_url", sa.String(2048), nullable=True))
    op.add_column("cv_profiles", sa.Column("search_ingest_job_id", sa.String(64), nullable=True))
    op.create_index("ix_cv_profiles_search_ingest_job_id", "cv_profiles", ["search_ingest_job_id"])


def downgrade() -> None:
    op.drop_index("ix_cv_profiles_search_ingest_job_id", table_name="cv_profiles")
    op.drop_column("cv_profiles", "search_ingest_job_id")
    op.drop_column("cv_profiles", "callback_url")
