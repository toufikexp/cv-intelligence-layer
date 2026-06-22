"""Tests for enrich_profile.

Skills arrive already coded (the extractor resolves Gemini's canonical names to
catalog codes; SkillConnect sync-in supplies codes directly), so enrich_profile
only resolves language codes. It must never touch skills.
"""

from __future__ import annotations

from app.models.schemas import CandidateProfile, LanguageEntry, SkillEntry
from app.services.catalog_store import CatalogStore, normalize
from app.services.skill_resolver import enrich_profile


def _store(langs: dict[str, str] | None = None) -> CatalogStore:
    """Build a store seeded with language code->name maps (bypassing the DB load)."""
    s = CatalogStore()
    langs = langs or {}
    s._lang_code_to_name = dict(langs)
    s._lang_norm_to_code = {normalize(n): c for c, n in langs.items()}
    return s


def test_enrich_fills_language_code() -> None:
    store = _store(langs={"LG1": "English", "LG2": "French"})
    profile = CandidateProfile(
        languages=[
            LanguageEntry(language="English", proficiency="C2"),
            LanguageEntry(language="Arabic", proficiency="NATIVE"),
        ],
    )
    enrich_profile(profile, store)
    assert profile.languages[0].languageCode == "LG1"
    assert profile.languages[1].languageCode is None  # unmatched → None


def test_enrich_resolves_canonical_name_from_seeded_catalog() -> None:
    # Mirrors the real seed (French names). When Gemini picks the canonical name
    # from the predefined list ("Français"), it resolves to the catalog code.
    store = _store(langs={"fr": "Français", "en": "Anglais", "dz": "Arabe"})
    profile = CandidateProfile(
        languages=[
            LanguageEntry(language="Français", proficiency="C1"),
            LanguageEntry(language="Anglais", proficiency="B2"),
        ],
    )
    enrich_profile(profile, store)
    assert profile.languages[0].languageCode == "fr"
    assert profile.languages[1].languageCode == "en"


def test_enrich_does_not_overwrite_existing_language_code() -> None:
    store = _store(langs={"LG1": "English"})
    profile = CandidateProfile(
        languages=[LanguageEntry(language="English", languageCode="PRESET")],
    )
    enrich_profile(profile, store)
    assert profile.languages[0].languageCode == "PRESET"


def test_enrich_leaves_skills_untouched() -> None:
    store = _store()
    profile = CandidateProfile(
        skills=[SkillEntry(skill="SK1", score="EXPERT"), SkillEntry(skill="SK2")],
    )
    enrich_profile(profile, store)
    assert [s.skill for s in profile.skills] == ["SK1", "SK2"]
    assert profile.skills[0].score == "EXPERT"


def test_enrich_empty_profile_no_error() -> None:
    store = _store()
    profile = CandidateProfile()
    enrich_profile(profile, store)
    assert profile.skills == []
    assert profile.languages == []
