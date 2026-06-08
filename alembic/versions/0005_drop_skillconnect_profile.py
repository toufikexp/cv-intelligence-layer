"""Drop the now-redundant cv_profiles.skillconnect_profile column.

The integration collapsed to ONE SkillConnect-native CandidateProfile model
stored in ``profile_data``. The separate ``skillconnect_profile`` JSONB column
(added in 0004 to hold a verbatim coded payload) is no longer written or read
by any code path, so it is dropped here.

Online-safe: the column is nullable and unused, so dropping it does not lock
existing rows or affect serving traffic. The downgrade re-adds it as a nullable
column (data is not recoverable, which is acceptable — it was redundant).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_drop_skillconnect_profile"
down_revision = "0004_skillconnect_catalogs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("cv_profiles", "skillconnect_profile")


def downgrade() -> None:
    op.add_column(
        "cv_profiles",
        sa.Column("skillconnect_profile", JSONB(), nullable=True),
    )
