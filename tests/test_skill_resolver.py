"""Tests for the SkillConnect coded payload <-> internal profile resolver."""

from __future__ import annotations

from app.models.schemas import CandidateProfile, LanguageEntry
from app.services.catalog_store import CatalogStore, normalize
from app.services.skill_resolver import coded_payload_to_profile, profile_to_coded_projection


def _store(skills: dict[str, str], estabs: dict[str, str] | None = None,
           langs: dict[str, str] | None = None) -> CatalogStore:
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


def test_coded_payload_resolves_skill_codes_to_names() -> None:
    store = _store({"SK1": "Python", "SK2": "SQL"})
    payload = {
        "employee": {"firstname": "Amina", "lastname": "Bensaid", "email": "a@x.com",
                     "function": "Data Engineer"},
        "skills": [{"skill": "SK1"}, {"skill": "SK2"}, {"skill": "UNKNOWN"}],
        "summary": "Engineer.",
    }
    profile = coded_payload_to_profile(payload, store)
    assert profile.name == "Amina Bensaid"
    assert profile.email == "a@x.com"
    assert profile.current_title == "Data Engineer"
    # Unknown code is dropped from the engine view (never fabricated).
    assert profile.skills == ["Python", "SQL"]


def test_coded_payload_maps_education_and_languages() -> None:
    store = _store({}, estabs={"ES1": "USTHB"})
    payload = {
        "employee": {"firstname": "Sam", "lastname": "Lee"},
        "educations": [{"establishment": "ES1", "typeEducation": "Master", "fieldOfStudy": "CS",
                        "dateGraduation": "2018"}],
        "languages": [{"language": "English", "proficiency": "C2"},
                      {"language": "French", "proficiency": "B1"}],
    }
    profile = coded_payload_to_profile(payload, store)
    assert profile.education[0].institution == "USTHB"
    assert profile.education[0].degree == "Master"
    # CEFR maps onto the coarse internal scale.
    assert profile.languages[0] == LanguageEntry(language="English", level="fluent")
    assert profile.languages[1] == LanguageEntry(language="French", level="intermediate")


def test_coded_payload_missing_name_falls_back_to_unknown() -> None:
    profile = coded_payload_to_profile({"skills": []}, _store({}))
    assert profile.name == "Unknown"
    assert profile.skills == []


def test_projection_matches_names_to_codes_unmatched_null() -> None:
    store = _store({"SK1": "Python"}, langs={"LG1": "English"})
    profile = CandidateProfile(
        name="Amina",
        skills=["Python", "Rust"],
        languages=[LanguageEntry(language="English", level="native")],
    )
    proj = profile_to_coded_projection(profile, store)
    by_name = {s["name"]: s["skill"] for s in proj["skills"]}
    assert by_name["Python"] == "SK1"
    assert by_name["Rust"] is None  # unmatched -> null code, name preserved
    assert proj["languages"][0]["languageCode"] == "LG1"
    assert proj["languages"][0]["proficiency"] == "NATIVE"


def test_roundtrip_codes_preserved_through_resolver() -> None:
    store = _store({"SK1": "Python", "SK2": "SQL"})
    payload = {"employee": {"firstname": "A", "lastname": "B"},
               "skills": [{"skill": "SK1"}, {"skill": "SK2"}]}
    profile = coded_payload_to_profile(payload, store)
    proj = profile_to_coded_projection(profile, store)
    codes = sorted(s["skill"] for s in proj["skills"])
    assert codes == ["SK1", "SK2"]
