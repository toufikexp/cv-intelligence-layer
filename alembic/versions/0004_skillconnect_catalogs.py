"""SkillConnect integration: catalog tables + skillconnect_profile column

Revision ID: 0004_skillconnect_catalogs
Revises: 0003_external_id_required
Create Date: 2026-06-08

Additive and online-safe: new tables + a nullable JSONB column. Existing rows
are untouched and old code ignores the new column, so this applies while
production serves traffic and is inert on rollback.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_skillconnect_catalogs"
down_revision = "0003_external_id_required"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cv_profiles",
        sa.Column("skillconnect_profile", JSONB(), nullable=True),
    )

    op.create_table(
        "skillconnect_skills",
        sa.Column("code", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("external_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_skillconnect_skills_name", "skillconnect_skills", ["name"])

    op.create_table(
        "skillconnect_establishments",
        sa.Column("code", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=512), nullable=False),
    )
    op.create_index(
        "ix_skillconnect_establishments_name", "skillconnect_establishments", ["name"]
    )

    op.create_table(
        "skillconnect_languages",
        sa.Column("code", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
    )
    op.create_index("ix_skillconnect_languages_name", "skillconnect_languages", ["name"])


def downgrade() -> None:
    op.drop_index("ix_skillconnect_languages_name", table_name="skillconnect_languages")
    op.drop_table("skillconnect_languages")
    op.drop_index(
        "ix_skillconnect_establishments_name", table_name="skillconnect_establishments"
    )
    op.drop_table("skillconnect_establishments")
    op.drop_index("ix_skillconnect_skills_name", table_name="skillconnect_skills")
    op.drop_table("skillconnect_skills")
    op.drop_column("cv_profiles", "skillconnect_profile")
