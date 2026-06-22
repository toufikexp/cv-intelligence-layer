"""Tests for the in-process SkillConnect catalog store."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.catalog_store import CatalogStore, normalize


def _result(rows: list[object]) -> MagicMock:
    res = MagicMock()
    res.scalars.return_value.all.return_value = rows
    return res


def _mock_db(skills: list[object], estabs: list[object], langs: list[object]) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_result(skills), _result(estabs), _result(langs)])
    return db


def test_normalize_collapses_case_and_punctuation() -> None:
    assert normalize("  Node.js  ") == "node js"
    assert normalize("C++") == "c"
    assert normalize("Machine   Learning") == "machine learning"


@pytest.mark.asyncio
async def test_load_from_db_populates_bidirectional_maps() -> None:
    store = CatalogStore()
    db = _mock_db(
        skills=[SimpleNamespace(code="SK1", name="Python"), SimpleNamespace(code="SK2", name="Node.js")],
        estabs=[SimpleNamespace(code="ES1", name="USTHB")],
        langs=[SimpleNamespace(code="LG1", name="English")],
    )
    await store.load_from_db(db)

    assert store.skill_name("SK1") == "Python"
    assert store.skill_code("python") == "SK1"
    # Normalized lookup tolerates punctuation/case differences.
    assert store.skill_code("NODE JS") == "SK2"
    assert store.establishment_code("usthb") == "ES1"
    assert store.language_name("LG1") == "English"
    assert store.skill_count == 2


@pytest.mark.asyncio
async def test_skill_names_block_is_names_only_sorted() -> None:
    store = CatalogStore()
    db = _mock_db(
        skills=[SimpleNamespace(code="B", name="SQL"), SimpleNamespace(code="A", name="Python")],
        estabs=[],
        langs=[],
    )
    await store.load_from_db(db)
    block = store.skill_names_block()
    assert block == "Python\nSQL"  # sorted, names only
    # No codes leak into the LLM-facing block.
    assert "(" not in block and "SK" not in block


def test_skill_names_block_placeholder_when_empty() -> None:
    assert CatalogStore().skill_names_block() == "(catalog unavailable)"


@pytest.mark.asyncio
async def test_languages_block_is_names_only_sorted() -> None:
    store = CatalogStore()
    db = _mock_db(
        skills=[],
        estabs=[],
        langs=[SimpleNamespace(code="fr", name="Français"), SimpleNamespace(code="en", name="Anglais")],
    )
    await store.load_from_db(db)
    block = store.languages_block()
    assert block == "Anglais\nFrançais"  # sorted, names only — no codes


def test_languages_block_placeholder_when_empty() -> None:
    assert CatalogStore().languages_block() == "(list unavailable)"


@pytest.mark.asyncio
async def test_fingerprint_changes_with_catalog_content() -> None:
    store = CatalogStore()
    await store.load_from_db(_mock_db([SimpleNamespace(code="SK1", name="Python")], [], []))
    fp1 = store.fingerprint
    await store.load_from_db(
        _mock_db([SimpleNamespace(code="SK1", name="Python"), SimpleNamespace(code="SK2", name="SQL")], [], [])
    )
    fp2 = store.fingerprint
    assert fp1 and fp2 and fp1 != fp2


@pytest.mark.asyncio
async def test_unknown_code_or_name_returns_none() -> None:
    store = CatalogStore()
    await store.load_from_db(_mock_db([SimpleNamespace(code="SK1", name="Python")], [], []))
    assert store.skill_name("NOPE") is None
    assert store.skill_code("Rust") is None
