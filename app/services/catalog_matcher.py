from __future__ import annotations

import json
import logging
import unicodedata
from pathlib import Path
from typing import Any

logger = logging.getLogger("cv_layer.catalog_matcher")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "skillconnect"


def _normalize_key(s: str) -> str:
    """Accent-insensitive, case-insensitive normalization for matching."""
    nfkd = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.lower().strip()


class CatalogMatcher:
    """In-memory catalog lookups for SkillConnect code<->name resolution."""

    def __init__(self) -> None:
        self._skills_by_code: dict[str, str] = {}
        self._skills_by_name: dict[str, str] = {}
        self._establishments_by_code: dict[str, str] = {}
        self._establishments_by_name: dict[str, str] = {}
        self._languages_by_code: dict[str, str] = {}
        self._languages_by_name: dict[str, str] = {}
        self._skill_names_list: list[str] = []

    def load(self) -> None:
        self._load_catalog(
            _DATA_DIR / "skills.json",
            self._skills_by_code,
            self._skills_by_name,
        )
        self._skill_names_list = list(self._skills_by_code.values())
        self._load_catalog(
            _DATA_DIR / "establishments.json",
            self._establishments_by_code,
            self._establishments_by_name,
        )
        self._load_catalog(
            _DATA_DIR / "languages.json",
            self._languages_by_code,
            self._languages_by_name,
        )
        logger.info(
            "Catalogs loaded: %d skills, %d establishments, %d languages",
            len(self._skills_by_code),
            len(self._establishments_by_code),
            len(self._languages_by_code),
        )

    def _load_catalog(
        self,
        path: Path,
        by_code: dict[str, str],
        by_name: dict[str, str],
    ) -> None:
        if not path.exists():
            logger.warning("Catalog file not found: %s", path)
            return
        items: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        for item in items:
            code = item["code"]
            name = item["name"]
            by_code[code] = name
            by_name[_normalize_key(name)] = code

    # --- Skill lookups ---

    def skill_code(self, name: str) -> str | None:
        return self._skills_by_name.get(_normalize_key(name))

    def skill_name(self, code: str) -> str | None:
        return self._skills_by_code.get(code)

    @property
    def skill_names(self) -> list[str]:
        return self._skill_names_list

    # --- Establishment lookups ---

    def establishment_code(self, name: str) -> str | None:
        return self._establishments_by_name.get(_normalize_key(name))

    def establishment_name(self, code: str) -> str | None:
        return self._establishments_by_code.get(code)

    # --- Language lookups ---

    def language_code(self, name: str) -> str | None:
        return self._languages_by_name.get(_normalize_key(name))

    def language_name(self, code: str) -> str | None:
        return self._languages_by_code.get(code)


_instance: CatalogMatcher | None = None


def get_catalog_matcher() -> CatalogMatcher:
    global _instance
    if _instance is None:
        _instance = CatalogMatcher()
        _instance.load()
    return _instance
