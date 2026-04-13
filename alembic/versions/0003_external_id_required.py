"""Make cv_profiles.external_id required and unique per collection

Revision ID: 0003_external_id_required
Revises: 0002_webhook_support
Create Date: 2026-04-13

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_external_id_required"
down_revision = "0002_webhook_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill legacy rows: rows predating this migration may have
    # external_id IS NULL. They were indexed in Semantic Search against
    # their file_hash (the old fallback), so reuse file_hash here — this
    # keeps backfilled rows searchable without re-indexing.
    op.execute("UPDATE cv_profiles SET external_id = file_hash WHERE external_id IS NULL")

    op.alter_column(
        "cv_profiles",
        "external_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.create_index("ix_cv_profiles_external_id", "cv_profiles", ["external_id"])
    op.create_unique_constraint(
        "uq_cv_profiles_collection_external_id",
        "cv_profiles",
        ["collection_id", "external_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_cv_profiles_collection_external_id",
        "cv_profiles",
        type_="unique",
    )
    op.drop_index("ix_cv_profiles_external_id", table_name="cv_profiles")
    op.alter_column(
        "cv_profiles",
        "external_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )
