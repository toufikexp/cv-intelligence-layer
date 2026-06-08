from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Establishment, Language, Skill

logger = logging.getLogger("cv_layer.catalog")


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — for fuzzy name matching."""
    t = text.lower().strip()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


class CatalogStore:
    """In-process cache of the SkillConnect catalogs.

    Skills are refreshed from the SkillConnect API; establishments/languages are
    loaded from their (manually seeded) tables. Both api/worker processes read
    the same DB tables, so the tables are the durable shared copy and these dicts
    are a per-process memo.
    """

    def __init__(self) -> None:
        self._skill_code_to_name: dict[str, str] = {}
        self._skill_norm_to_code: dict[str, str] = {}
        self._estab_code_to_name: dict[str, str] = {}
        self._estab_norm_to_code: dict[str, str] = {}
        self._lang_code_to_name: dict[str, str] = {}
        self._lang_norm_to_code: dict[str, str] = {}
        self._fingerprint: str = ""

    # --- lookups -----------------------------------------------------------
    def skill_name(self, code: str) -> str | None:
        return self._skill_code_to_name.get(code)

    def skill_code(self, name: str) -> str | None:
        return self._skill_norm_to_code.get(normalize(name))

    def establishment_name(self, code: str) -> str | None:
        return self._estab_code_to_name.get(code)

    def establishment_code(self, name: str) -> str | None:
        return self._estab_norm_to_code.get(normalize(name))

    def language_name(self, code: str) -> str | None:
        return self._lang_code_to_name.get(code)

    def language_code(self, name: str) -> str | None:
        return self._lang_norm_to_code.get(normalize(name))

    def skills_catalog_lines(self) -> list[str]:
        """`name (code)` lines for inclusion in the Gemini extraction prompt."""
        return [f"{name} ({code})" for code, name in sorted(self._skill_code_to_name.items())]

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def skill_count(self) -> int:
        return len(self._skill_code_to_name)

    # --- loading -----------------------------------------------------------
    async def load_from_db(self, db: AsyncSession) -> None:
        """Populate the in-process dicts from the catalog tables."""
        skills = (await db.execute(select(Skill))).scalars().all()
        self._skill_code_to_name = {s.code: s.name for s in skills}
        self._skill_norm_to_code = {normalize(s.name): s.code for s in skills}
        self._fingerprint = self._compute_fingerprint(skills)

        estabs = (await db.execute(select(Establishment))).scalars().all()
        self._estab_code_to_name = {e.code: e.name for e in estabs}
        self._estab_norm_to_code = {normalize(e.name): e.code for e in estabs}

        langs = (await db.execute(select(Language))).scalars().all()
        self._lang_code_to_name = {lg.code: lg.name for lg in langs}
        self._lang_norm_to_code = {normalize(lg.name): lg.code for lg in langs}

    async def refresh_skills_from_api(self, db: AsyncSession, rows: list[dict[str, Any]]) -> bool:
        """Upsert fetched skill rows into the table, reload dicts. Returns True if changed."""
        old_fingerprint = self._fingerprint
        for row in rows:
            code = row.get("code")
            name = row.get("name")
            if not code or not name:
                continue
            stmt = pg_insert(Skill).values(
                code=code,
                name=name,
                category=row.get("category"),
                external_id=row.get("id"),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["code"],
                set_={"name": name, "category": row.get("category"), "external_id": row.get("id")},
            )
            await db.execute(stmt)
        await db.commit()
        await self.load_from_db(db)
        return self._fingerprint != old_fingerprint

    @staticmethod
    def _compute_fingerprint(skills: Any) -> str:
        payload = sorted((s.code, s.name) for s in skills)
        return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


# Process-wide singleton.
catalog_store = CatalogStore()
