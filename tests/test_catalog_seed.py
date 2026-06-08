"""Integrity checks for the SkillConnect catalog seed migration (0006).

These assert the embedded reference data is well-formed without needing a live
database: correct counts (221 skills / 67 establishments / 5 languages), unique
primary-key codes, and no blank code/name values.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0006_seed_skillconnect_catalogs.py"
)


@pytest.fixture(scope="module")
def seed():
    spec = importlib.util.spec_from_file_location("seed_0006", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_counts_match_source_document(seed) -> None:
    assert len(seed.SKILLS) == 221
    assert len(seed.ESTABLISHMENTS) == 67
    assert len(seed.LANGUAGES) == 5


def test_skill_codes_unique_and_nonblank(seed) -> None:
    codes = [code for code, *_ in seed.SKILLS]
    assert len(set(codes)) == len(codes)
    assert all(code and name for code, name, *_ in seed.SKILLS)


def test_establishment_codes_unique_and_nonblank(seed) -> None:
    codes = [code for code, _ in seed.ESTABLISHMENTS]
    assert len(set(codes)) == len(codes)
    assert all(code and name for code, name in seed.ESTABLISHMENTS)


def test_language_codes_unique_and_nonblank(seed) -> None:
    codes = [code for code, _ in seed.LANGUAGES]
    assert len(set(codes)) == len(codes)
    assert all(code and name for code, name in seed.LANGUAGES)


def test_duplicate_source_codes_disambiguated(seed) -> None:
    # USA and UTI each appear twice in the source for distinct universities;
    # the second occurrence is suffixed _2 so both rows survive.
    by_code = dict(seed.ESTABLISHMENTS)
    assert "USA" in by_code and "USA_2" in by_code
    assert by_code["USA"] != by_code["USA_2"]
    assert "UTI" in by_code and "UTI_2" in by_code
    assert by_code["UTI"] != by_code["UTI_2"]


def test_migration_chain(seed) -> None:
    assert seed.revision == "0006_seed_skillconnect_catalogs"
    assert seed.down_revision == "0005_drop_skillconnect_profile"
