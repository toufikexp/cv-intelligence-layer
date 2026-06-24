"""Tests for enrich_profile.

enrich_profile is the single catalog-resolution chokepoint: it validates skills
(name->code, valid code kept, off-catalog dropped), resolves establishment codes
(institution free-text -> establishment code), and fills language codes.
"""

from __future__ import annotations

from app.models.schemas import (
    CandidateProfile,
    EducationEntry,
    LanguageEntry,
    SkillEntry,
)
from app.services.catalog_store import CatalogStore, normalize
from app.services.skill_resolver import enrich_profile


def _store(
    langs: dict[str, str] | None = None,
    skills: dict[str, str] | None = None,
    estabs: dict[str, str] | None = None,
) -> CatalogStore:
    """Build a store seeded with code->name maps (bypassing the DB load)."""
    s = CatalogStore()
    langs = langs or {}
    s._lang_code_to_name = dict(langs)
    s._lang_norm_to_code = {normalize(n): c for c, n in langs.items()}
    skills = skills or {}
    s._skill_code_to_name = dict(skills)
    s._skill_norm_to_code = {normalize(n): c for c, n in skills.items()}
    estabs = estabs or {}
    s._estab_code_to_name = dict(estabs)
    s._estab_norm_to_code = {normalize(n): c for c, n in estabs.items()}
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


def test_enrich_keeps_valid_skill_codes() -> None:
    store = _store(skills={"SK1": "Python", "SK2": "Docker"})
    profile = CandidateProfile(
        skills=[SkillEntry(skill="SK1", score="EXPERT"), SkillEntry(skill="SK2")],
    )
    enrich_profile(profile, store)
    assert [s.skill for s in profile.skills] == ["SK1", "SK2"]
    assert profile.skills[0].score == "EXPERT"


def test_enrich_resolves_skill_name_to_code() -> None:
    store = _store(skills={"SK1": "Python"})
    profile = CandidateProfile(skills=[SkillEntry(skill="Python", score="ADVANCED")])
    enrich_profile(profile, store)
    assert profile.skills[0].skill == "SK1"
    assert profile.skills[0].score == "ADVANCED"


def test_enrich_drops_off_catalog_skills() -> None:
    store = _store(skills={"SK1": "Python"})
    profile = CandidateProfile(
        skills=[SkillEntry(skill="Python"), SkillEntry(skill="Rust")],  # Rust off-catalog
    )
    enrich_profile(profile, store)
    assert [s.skill for s in profile.skills] == ["SK1"]


def test_enrich_resolves_establishment_code_from_institution() -> None:
    store = _store(estabs={"ES1": "USTHB"})
    profile = CandidateProfile(
        educations=[EducationEntry(institution="USTHB", fieldOfStudy="Télécoms")],
    )
    enrich_profile(profile, store)
    assert profile.educations[0].establishment == "ES1"
    assert profile.educations[0].institution == "USTHB"  # free text kept


def test_enrich_unmatched_establishment_is_none() -> None:
    store = _store(estabs={"ES1": "USTHB"})
    profile = CandidateProfile(
        educations=[EducationEntry(institution="Some Unknown School")],
    )
    enrich_profile(profile, store)
    assert profile.educations[0].establishment is None
    assert profile.educations[0].institution == "Some Unknown School"


def test_enrich_empty_profile_no_error() -> None:
    store = _store()
    profile = CandidateProfile()
    enrich_profile(profile, store)
    assert profile.skills == []
    assert profile.languages == []
