"""Repair corrupted skill names seeded by 0006.

The original 0006 was generated from the source ``skillConnect_details_v_1.0.docx``
with a column-shift bug: from skill #101 onward the ``name`` column held the
*code* and the real name was pushed into ``category``. 121 of 221 rows landed in
the DB with ``name == code`` (e.g. ``DATA_AI_ML`` instead of
``Machine Learning - Artificial Intelligence``), which broke catalog resolution
(``skill_code(real_name)`` returned None) and fed Gemini garbage vocabulary.

0006 has since been corrected at the source. This migration re-upserts the
authoritative 221 skills so databases that already ran the corrupted 0006 get
repaired by ``alembic upgrade head`` (the upsert is idempotent; fresh deploys
where 0006 is already correct see this as a no-op).

Reads the corrected SKILLS list from the 0006 module so there is a single
source of truth (the module filename starts with a digit, so it is loaded via
importlib rather than a normal import).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert as pg_insert

revision = "0007_fix_corrupted_skill_names"
down_revision = "0006_seed_skillconnect_catalogs"
branch_labels = None
depends_on = None


def _load_corrected_skills() -> list[tuple[str, str, str | None, int | None]]:
    """Load the corrected SKILLS list from the 0006 migration module."""
    path = Path(__file__).with_name("0006_seed_skillconnect_catalogs.py")
    spec = importlib.util.spec_from_file_location("_seed_0006", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SKILLS


_skills_tbl = sa.table(
    "skillconnect_skills",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    sa.column("category", sa.String),
    sa.column("external_id", sa.Integer),
)


def upgrade() -> None:
    conn = op.get_bind()
    for code, name, category, external_id in _load_corrected_skills():
        stmt = pg_insert(_skills_tbl).values(
            code=code, name=name, category=category, external_id=external_id
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"],
            set_=dict(
                name=stmt.excluded.name,
                category=stmt.excluded.category,
                external_id=stmt.excluded.external_id,
            ),
        )
        conn.execute(stmt)


def downgrade() -> None:
    # No-op: the corrected names are the authoritative data. There is nothing
    # safe to roll back to (the prior state was corrupted).
    pass
