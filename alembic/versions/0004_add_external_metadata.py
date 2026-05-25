"""Add external_metadata JSONB column to cv_profiles.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cv_profiles", sa.Column("external_metadata", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("cv_profiles", "external_metadata")
