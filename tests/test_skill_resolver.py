"""Tests for the enrich_profile resolver (fills codes ↔ names in place)."""

from __future__ import annotations

from app.models.schemas import CandidateProfile, LanguageEntry, SkillEntry
from app.services.catalog_store import CatalogStore, normalize
from app.services.skill_resolver import enrich_profile


def _store(
    skills: dict[str, str],
    estabs: dict[str, str] | None = None,
    langs: dict[str, str] | None = None,
) -> CatalogStore:
    """Build a store seeded with code->name maps (bypassing the DB load)."""
    s = CatalogStore()
    s._skill_code_to_name = dict(skills)
    s._skill_norm_to_code = {normalize(n): c for c, n in skills.items()}
    estabs = estabs or {}
    s._estab_code_to_name = dict(estabs)
    s._estab_norm_to_code = {normalize(n): c for c, n in estabs.items()}
    langs = langs or {}
    s._lang_code_to_name = dict(langs)
    s._lang_norm_to_code = {normalize(n): c for c, n in langs.items()}
    return s


def test_enrich_fills_name_from_skill_code() -> None:
    store = _store({"SK1": "Python", "SK2": "SQL"})
    profile = CandidateProfile(
        skills=[
            SkillEntry(skill="SK1"),
            SkillEntry(skill="SK2"),
            SkillEntry(skill="UNKNOWN"),
        ],
    )
    enrich_profile(profile, store)
    assert profile.skills[0].name == "Python"
    assert profile.skills[1].name == "SQL"
    assert profile.skills[2].name is None  # unmatched → None


def test_enrich_fills_code_from_skill_name() -> None:
    store = _store({"SK1": "Python", "SK2": "SQL"})
    profile = CandidateProfile(
        skills=[
            SkillEntry(name="Python"),
            SkillEntry(name="Rust"),
        ],
    )
    enrich_profile(profile, store)
    assert profile.skills[0].skill == "SK1"
    assert profile.skills[1].skill is None  # unmatched → None


def test_enrich_fills_language_code() -> None:
    store = _store({}, langs={"LG1": "English", "LG2": "French"})
    profile = CandidateProfile(
        languages=[
            LanguageEntry(language="English", proficiency="C2"),
            LanguageEntry(language="Arabic", proficiency="NATIVE"),
        ],
    )
    enrich_profile(profile, store)
    assert profile.languages[0].languageCode == "LG1"
    assert profile.languages[1].languageCode is None  # unmatched


def test_enrich_does_not_overwrite_existing() -> None:
    store = _store({"SK1": "Python"})
    profile = CandidateProfile(
        skills=[SkillEntry(skill="SK1", name="AlreadySet")],
    )
    enrich_profile(profile, store)
    assert profile.skills[0].name == "AlreadySet"


def test_enrich_empty_profile_no_error() -> None:
    store = _store({})
    profile = CandidateProfile()
    enrich_profile(profile, store)
    assert profile.skills == []
    assert profile.languages == []


def test_roundtrip_codes_preserved() -> None:
    store = _store({"SK1": "Python", "SK2": "SQL"})
    profile = CandidateProfile(
        skills=[SkillEntry(name="Python"), SkillEntry(name="SQL")],
    )
    enrich_profile(profile, store)
    codes = sorted(s.skill for s in profile.skills if s.skill)
    assert codes == ["SK1", "SK2"]
