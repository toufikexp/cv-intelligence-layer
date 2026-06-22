"""Tests for entity extraction, phone normalization, and PII redaction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.schemas import CandidateProfile
from app.services.entity_extractor import (
    EntityExtractor,
    _DOB_AGE_RE,
    _extract_phone,
    _extract_pii_entities,
    _is_section_header,
    _normalize_phone,
    _redact_pii,
    _strip_header_zone,
    load_spacy_models,
    usable_char_count,
)


@pytest.fixture(scope="session", autouse=True)
def _ensure_spacy_models() -> None:
    """Load spaCy models once for the entire test session."""
    load_spacy_models()


class TestPhoneNormalization:
    def test_algerian_mobile(self) -> None:
        assert _normalize_phone("0555 123 456") == "+213 555 123 456"

    def test_algerian_mobile_no_spaces(self) -> None:
        assert _normalize_phone("0555123456") == "+213 555 123 456"

    def test_algerian_06(self) -> None:
        assert _normalize_phone("0612345678") == "+213 612 345 678"

    def test_algerian_07(self) -> None:
        assert _normalize_phone("0712345678") == "+213 712 345 678"

    def test_french_mobile(self) -> None:
        result = _normalize_phone("0612345678")
        assert result.startswith("+213") or result.startswith("+33")

    def test_international_kept(self) -> None:
        assert _normalize_phone("+44 7911 123456") == "+44 7911 123456"

    def test_already_international_213(self) -> None:
        assert _normalize_phone("+213 555 123 456") == "+213 555 123 456"

    def test_unknown_format_kept(self) -> None:
        assert _normalize_phone("12345") == "12345"


class TestRegexExtraction:
    def test_email_found(self) -> None:
        from app.services.entity_extractor import _EMAIL_RE, _first_match

        assert _first_match(_EMAIL_RE, "Contact: user@example.com for info") == "user@example.com"

    def test_phone_found(self) -> None:
        from app.services.entity_extractor import _PHONE_RE, _first_match

        result = _first_match(_PHONE_RE, "Call 0555 123 456 now")
        assert result is not None
        assert "555" in result


@pytest.mark.asyncio
async def test_extract_with_mocked_llm(mock_llm_client: AsyncMock) -> None:
    extractor = EntityExtractor(mock_llm_client)
    profile = await extractor.extract(
        cv_text="Jean Dupont\njean@example.com\n0555123456\nPython developer",
        detected_language="fr",
        extraction_notes="Clean text extraction from document",
    )
    assert isinstance(profile, CandidateProfile)
    # Employee block has PII from local extraction
    assert profile.employee is not None
    assert profile.employee.email == "jean@example.com"
    assert profile.employee.phone is not None
    assert profile.employee.phone.startswith("+213")


@pytest.mark.asyncio
async def test_regex_email_overrides_llm(mock_llm_client: AsyncMock) -> None:
    extractor = EntityExtractor(mock_llm_client)
    profile = await extractor.extract(
        cv_text="real@real.com is the email",
        detected_language="en",
        extraction_notes="Clean",
    )
    assert profile.employee is not None
    assert profile.employee.email == "real@real.com"


class TestDobAgeRegex:
    def test_french_dob(self) -> None:
        assert _DOB_AGE_RE.search("Né le 15/03/1990")

    def test_french_female_dob(self) -> None:
        assert _DOB_AGE_RE.search("Née le 22-05-1985")

    def test_english_dob(self) -> None:
        assert _DOB_AGE_RE.search("Date of birth: 1990-03-15")

    def test_age_french(self) -> None:
        assert _DOB_AGE_RE.search("28 ans")

    def test_age_english(self) -> None:
        assert _DOB_AGE_RE.search("32 years old")

    def test_age_label(self) -> None:
        assert _DOB_AGE_RE.search("Age: 35")

    def test_no_false_positive_on_year(self) -> None:
        assert not _DOB_AGE_RE.search("2022")

    def test_no_false_positive_on_experience(self) -> None:
        assert not _DOB_AGE_RE.search("5 years of experience in Python")


class TestSpacyPiiExtraction:
    def test_french_name_and_location(self) -> None:
        text = "Ahmed Benali\nIngénieur Logiciel\nAlger, Algérie\nahmed@email.com"
        pii = _extract_pii_entities(text, "fr")
        assert pii["name"] is not None
        assert "benali" in pii["name"].lower() or "ahmed" in pii["name"].lower()
        assert pii["location"] is not None

    def test_english_name_and_location(self) -> None:
        text = "Sarah Johnson\nSoftware Developer\nLondon, UK\nsarah@email.com"
        pii = _extract_pii_entities(text, "en")
        assert pii["name"] is not None
        assert "johnson" in pii["name"].lower() or "sarah" in pii["name"].lower()

    def test_dob_near_keyword(self) -> None:
        text = "Jean Dupont\nNé le 15 mars 1990\nAlger"
        pii = _extract_pii_entities(text, "fr")
        assert pii["name"] is not None

    def test_no_entities_in_generic_text(self) -> None:
        header = "some random words and numbers 123\nno real entities here"
        pii = _extract_pii_entities(header, "en")
        assert pii["name"] is None
        assert pii["location"] is None

    def test_label_word_not_used_as_location(self) -> None:
        text = (
            "PRÉNOM NOM\n"
            "Adresse : Alger – Algérie\n"
            "Email : prenom.nom@email.com\n"
            "\n"
            "PROFIL PROFESSIONNEL\n"
            "Ingénieur RAN avec amélioration de la qualité de service continue."
        )
        pii = _extract_pii_entities(text, "fr")
        assert pii["location"] != "Adresse"
        assert "Alger" in pii["location_terms"]
        assert "Algérie" in pii["location_terms"]

    def test_name_fallback_for_all_caps_placeholder(self) -> None:
        text = (
            "PRÉNOM NOM\n"
            "Adresse : Alger\n"
            "\n"
            "PROFIL\n"
            "amélioration de la qualité de service continue"
        )
        pii = _extract_pii_entities(text, "fr")
        assert pii["name"] == "PRÉNOM NOM"

    def test_location_fully_redacted_end_to_end(self) -> None:
        text = (
            "PRÉNOM NOM\n"
            "Adresse : Alger – Algérie\n"
            "\n"
            "PROFIL\n"
            "Ingénieur réseau expérimenté."
        )
        pii = _extract_pii_entities(text, "fr")
        redacted = _redact_pii(
            text, pii["person_terms"], pii["location_terms"], pii["dob"]
        )
        assert "Alger" not in redacted
        assert "Algérie" not in redacted


class TestPiiRedaction:
    def test_redacts_name_throughout(self) -> None:
        text = "Jean Dupont\nExperience at Acme\nReference: Jean Dupont"
        result = _redact_pii(text, ["Jean Dupont"], [], None)
        assert "Jean Dupont" not in result
        assert result.count("[REDACTED_NAME]") == 2

    def test_redacts_location(self) -> None:
        text = "Ahmed\nAlger, Algérie\nSkills: Python"
        result = _redact_pii(text, ["Ahmed"], ["Alger"], None)
        assert "Ahmed" not in result
        assert "[REDACTED_NAME]" in result
        assert "[REDACTED_LOCATION]" in result

    def test_redacts_all_locations(self) -> None:
        text = "Adresse : Alger – Algérie"
        result = _redact_pii(text, [], ["Alger", "Algérie"], None)
        assert "Alger" not in result
        assert "Algérie" not in result
        assert result.count("[REDACTED_LOCATION]") == 2

    def test_redacts_email(self) -> None:
        text = "Contact: user@example.com"
        result = _redact_pii(text, [], [], None)
        assert "user@example.com" not in result
        assert "[REDACTED_EMAIL]" in result

    def test_redacts_phone(self) -> None:
        text = "Phone: +213 555 123 456"
        result = _redact_pii(text, [], [], None)
        assert "+213 555 123 456" not in result
        assert "[REDACTED_PHONE]" in result

    def test_redacts_urls(self) -> None:
        text = "Profile: https://linkedin.com/in/jdupont"
        result = _redact_pii(text, [], [], None)
        assert "linkedin.com" not in result
        assert "[REDACTED_URL]" in result

    def test_redacts_dob_regex(self) -> None:
        text = "Born: Né le 15/03/1990\nSkills: Python"
        result = _redact_pii(text, [], [], None)
        assert "15/03/1990" not in result
        assert "[REDACTED_DOB]" in result

    def test_redacts_dob_spacy(self) -> None:
        text = "Né le 15 mars 1990\nSkills: Python"
        result = _redact_pii(text, [], [], "15 mars 1990")
        assert "15 mars 1990" not in result

    def test_preserves_non_pii(self) -> None:
        text = "Skills: Python, SQL, Docker\nExperience: 5 years at Acme Corp"
        result = _redact_pii(text, [], [], None)
        assert "Python" in result
        assert "SQL" in result
        assert "Acme Corp" in result

    def test_full_cv_redaction(self) -> None:
        text = (
            "Jean Dupont\n"
            "Développeur Senior\n"
            "Alger, Algérie\n"
            "jean.dupont@email.com | +213 555 123 456\n"
            "https://linkedin.com/in/jdupont\n"
            "Né le 15/03/1990\n"
            "\n"
            "EXPÉRIENCE\n"
            "Acme Corp — Développeur (2020-2024)\n"
            "Python, FastAPI, PostgreSQL\n"
        )
        result = _redact_pii(text, ["Jean Dupont"], ["Alger", "Algérie"], None)
        assert "Jean Dupont" not in result
        assert "jean.dupont@email.com" not in result
        assert "+213 555 123 456" not in result
        assert "linkedin.com" not in result
        assert "15/03/1990" not in result
        assert "Développeur Senior" in result
        assert "Acme Corp" in result
        assert "Python" in result


@pytest.mark.asyncio
async def test_extract_merges_spacy_pii(mock_llm_client: AsyncMock) -> None:
    """Verify that spaCy-detected name is used (always, not just when LLM returns Unknown)."""
    extractor = EntityExtractor(mock_llm_client)
    profile = await extractor.extract(
        cv_text="Ahmed Benali\nahmed@email.com\n0555123456\nDéveloppeur Python\nAlger",
        detected_language="fr",
        extraction_notes="Clean text extraction from document",
    )
    assert isinstance(profile, CandidateProfile)
    assert profile.employee is not None
    assert profile.employee.email == "ahmed@email.com"


class TestOcrNameFallback:
    """OCR can leave the contact block empty (merged/garbled header). The name
    must still be recovered locally — never via the LLM."""

    def test_name_recovered_when_contact_block_empty(self) -> None:
        text = (
            "nicole. moore@gmail.com | +1 971 902 4932 | Dublin, Ireland "
            "https://linkedin./in/nicole-moore extra noise tokens padding\n"
            "Nicole Moore\n"
            "Process Engineer\n"
            "SUMMARY\n"
            "Experienced Process Engineer with 15+ years of expertise."
        )
        pii = _extract_pii_entities(text, "en")
        assert pii["name"] == "Nicole Moore"

    def test_fallback_stays_within_header_zone(self) -> None:
        text = (
            "PROFIL PROFESSIONNEL\n"
            "Nicole Moore\n"
            "Ingénieur expérimenté."
        )
        pii = _extract_pii_entities(text, "fr")
        assert pii["name"] is None


class TestSectionHeaderDetection:
    def test_exact_match(self) -> None:
        assert _is_section_header("EXPÉRIENCE")
        assert _is_section_header("  Formation  ")
        assert _is_section_header("Skills:")

    def test_multi_word_keyword_match(self) -> None:
        assert _is_section_header("EXPERIENCES PROFESSIONNELLES")
        assert _is_section_header("PROFIL PROFESSIONNEL")
        assert _is_section_header("Compétences Professionnelles")

    def test_rejects_name(self) -> None:
        assert not _is_section_header("Jean Dupont")
        assert not _is_section_header("Ahmed Benali")

    def test_rejects_empty(self) -> None:
        assert not _is_section_header("")
        assert not _is_section_header("   ")


class TestExtractPhone:
    def test_valid_phone(self) -> None:
        assert _extract_phone("Call 0555 123 456 now") is not None

    def test_skips_year_range(self) -> None:
        assert _extract_phone("2015-2017") is None

    def test_skips_short_number(self) -> None:
        assert _extract_phone("12345") is None

    def test_international_phone(self) -> None:
        result = _extract_phone("Phone: +213 555 123 456")
        assert result is not None
        assert "213" in result

    def test_year_range_not_redacted(self) -> None:
        text = "Études: 2015-2017\nPhone: +213 555 123 456"
        result = _redact_pii(text, [], [], None)
        assert "2015-2017" in result
        assert "[REDACTED_PHONE]" in result


class TestStripHeaderZone:
    def test_header_replaced_with_placeholder(self) -> None:
        text = (
            "Jean Dupont\n"
            "jean@email.com\n"
            "0555 123 456\n"
            "\n"
            "EXPÉRIENCE\n"
            "Acme Corp — Developer"
        )
        result = _strip_header_zone(text)
        assert result.startswith("[CONTACT_DETAILS_REDACTED]")
        assert "Jean Dupont" not in result
        assert "jean@email.com" not in result
        assert "EXPÉRIENCE" in result
        assert "Acme Corp" in result

    def test_no_header_when_section_first(self) -> None:
        text = "EXPÉRIENCE\nAcme Corp — Developer"
        result = _strip_header_zone(text)
        assert result == text

    def test_cap_at_8_lines(self) -> None:
        lines = [f"line {i}" for i in range(12)]
        lines.append("EXPÉRIENCE")
        text = "\n".join(lines)
        result = _strip_header_zone(text)
        assert result.startswith("[CONTACT_DETAILS_REDACTED]")

    def test_multi_word_section_header_detected(self) -> None:
        text = (
            "EXPERIENCES PROFESSIONNELLES\n"
            "Acme Corp — Developer"
        )
        result = _strip_header_zone(text)
        assert result == text


class TestPiiNeverReachesLlm:
    """Hard constraint: the text sent to Gemini must contain no PII from the header."""

    def test_standard_cv_header_stripped(self) -> None:
        text = (
            "Jean Dupont\n"
            "Développeur Senior\n"
            "Alger, Algérie\n"
            "jean.dupont@email.com | +213 555 123 456\n"
            "https://linkedin.com/in/jdupont\n"
            "Né le 15/03/1990\n"
            "\n"
            "EXPÉRIENCE\n"
            "Acme Corp — Développeur (2020-2024)\n"
        )
        pii = _extract_pii_entities(text, "fr")
        llm_input = _redact_pii(
            _strip_header_zone(text),
            pii["person_terms"],
            pii["location_terms"],
            pii["dob"],
        )
        assert "Jean Dupont" not in llm_input
        assert "jean.dupont@email.com" not in llm_input
        assert "Alger" not in llm_input
        assert "linkedin.com" not in llm_input
        assert "@" not in llm_input
        assert "[CONTACT_DETAILS_REDACTED]" in llm_input
        assert "Acme Corp" in llm_input

    def test_cv_starting_with_section_header(self) -> None:
        text = (
            "EXPERIENCES PROFESSIONNELLES\n"
            "Specialist Senior chez Acme Corp\n"
            "2015-2017\n"
        )
        pii = _extract_pii_entities(text, "fr")
        llm_input = _redact_pii(
            _strip_header_zone(text),
            pii["person_terms"],
            pii["location_terms"],
            pii["dob"],
        )
        assert "Specialist Senior" in llm_input
        assert "2015-2017" in llm_input

    def test_placeholder_cv_header_stripped(self) -> None:
        text = (
            "PRÉNOM NOM\n"
            "Adresse : Alger – Algérie\n"
            "Email : prenom.nom@email.com\n"
            "\n"
            "PROFIL PROFESSIONNEL\n"
            "Ingénieur RAN avec amélioration de la qualité."
        )
        pii = _extract_pii_entities(text, "fr")
        llm_input = _redact_pii(
            _strip_header_zone(text),
            pii["person_terms"],
            pii["location_terms"],
            pii["dob"],
        )
        assert "PRÉNOM NOM" not in llm_input
        assert "prenom.nom@email.com" not in llm_input
        assert "Alger" not in llm_input
        assert "[CONTACT_DETAILS_REDACTED]" in llm_input
        assert "amélioration" in llm_input


class TestUsableCharCount:
    def test_counts_alphanumeric(self) -> None:
        assert usable_char_count("Hello World 123") == 13

    def test_counts_accented(self) -> None:
        assert usable_char_count("Développeur à Alger") > 10

    def test_empty(self) -> None:
        assert usable_char_count("") == 0

    def test_only_symbols(self) -> None:
        assert usable_char_count("--- *** ###") == 0


@pytest.mark.asyncio
async def test_name_spacy_only_ignores_gemini(mock_llm_client: AsyncMock) -> None:
    """Name must come from spaCy, not Gemini — even when Gemini has a value."""
    extractor = EntityExtractor(mock_llm_client)
    profile = await extractor.extract(
        cv_text="EXPERIENCES PROFESSIONNELLES\nSpecialist Senior chez Acme\n2015-2017",
        detected_language="fr",
        extraction_notes="Clean",
    )
    assert profile.employee is not None
    assert profile.employee.firstname == "Unknown"


@pytest.mark.asyncio
async def test_extractor_resolves_skill_codes_and_drops_off_catalog() -> None:
    """Gemini returns canonical skill NAMES; the extractor resolves them to catalog
    codes ({skill: code, score}) and drops any name not in the catalog. No free-text
    `name` survives on the stored skill."""
    from app.services.catalog_store import catalog_store, normalize

    catalog_store._skill_code_to_name = {"SK1": "Python"}
    catalog_store._skill_norm_to_code = {normalize("Python"): "SK1"}

    llm = AsyncMock()

    async def _complete_json(*, prompt_key: str, variables: dict, **kwargs: object) -> dict:
        return {
            "summary": "dev",
            "function": "Engineer",
            "skills": [
                {"name": "Python", "score": "EXPERT"},
                {"name": "Rust", "score": "BASIC"},  # off-catalog → dropped
            ],
            "experiences": [],
            "educations": [],
            "languages": [],
        }

    llm.complete_json = _complete_json
    extractor = EntityExtractor(llm)
    profile = await extractor.extract(
        cv_text="EXPERIENCES\nEngineer at Acme\nPython, Rust",
        detected_language="en",
        extraction_notes="Clean",
    )

    assert [(s.skill, s.score) for s in profile.skills] == [("SK1", "EXPERT")]
    assert not hasattr(profile.skills[0], "name")


@pytest.mark.asyncio
async def test_phone_year_range_not_extracted(mock_llm_client: AsyncMock) -> None:
    """Year ranges like 2015-2017 must never be used as phone numbers."""
    extractor = EntityExtractor(mock_llm_client)
    profile = await extractor.extract(
        cv_text="EXPERIENCES PROFESSIONNELLES\nSpecialist Senior\n2015-2017\nPython, Docker",
        detected_language="fr",
        extraction_notes="Clean",
    )
    assert profile.employee is None or profile.employee.phone is None or "2015" not in (profile.employee.phone or "")
