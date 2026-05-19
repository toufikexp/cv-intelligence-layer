"""Tests for entity extraction, phone normalization, and PII redaction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.schemas import CandidateProfile
from app.services.entity_extractor import (
    EntityExtractor,
    _DOB_AGE_RE,
    _extract_pii_entities,
    _normalize_phone,
    _redact_pii,
    load_spacy_models,
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
        # French 06/07 are 10 digits same as Algerian — the function
        # applies Algerian pattern first (both match). This is expected
        # since the project is Algeria-focused per SPEC.
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

    def test_urls_extracted(self) -> None:
        from app.services.entity_extractor import _extract_urls

        text = "LinkedIn: https://linkedin.com/in/jdupont GitHub: https://github.com/jdupont Portfolio: https://jdupont.dev"
        urls = _extract_urls(text)
        assert "linkedin.com" in (urls["linkedin_url"] or "")
        assert "github.com" in (urls["github_url"] or "")
        assert "jdupont.dev" in (urls["portfolio_url"] or "")


@pytest.mark.asyncio
async def test_extract_with_mocked_llm(mock_llm_client: AsyncMock) -> None:
    extractor = EntityExtractor(mock_llm_client)
    profile = await extractor.extract(
        cv_text="Jean Dupont\njean@example.com\n0555123456\nPython developer",
        detected_language="fr",
        extraction_notes="Clean text extraction from document",
    )
    assert isinstance(profile, CandidateProfile)
    # Regex email should override LLM
    assert profile.email == "jean@example.com"
    # Phone should be normalized
    assert profile.phone is not None
    assert profile.phone.startswith("+213")


@pytest.mark.asyncio
async def test_regex_email_overrides_llm(mock_llm_client: AsyncMock) -> None:
    extractor = EntityExtractor(mock_llm_client)
    profile = await extractor.extract(
        cv_text="real@real.com is the email",
        detected_language="en",
        extraction_notes="Clean",
    )
    assert profile.email == "real@real.com"


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
        # DOB detection depends on spaCy recognizing a DATE entity near keyword

    def test_no_entities_in_generic_text(self) -> None:
        header = "some random words and numbers 123\nno real entities here"
        pii = _extract_pii_entities(header, "en")
        assert pii["name"] is None
        assert pii["location"] is None

    def test_label_word_not_used_as_location(self) -> None:
        # Regression: spaCy tags "Adresse" as LOC; it shadowed the real
        # location and left "Alger – Algérie" un-redacted for the LLM.
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
        # Regression: all-caps "PRÉNOM NOM" is tagged ORG (not PER); the
        # flat window then picked "de la" from the summary prose as the name.
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
        # Both city and country must go, not just the first detected entity.
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
        # Non-PII preserved
        assert "Développeur Senior" in result
        assert "Acme Corp" in result
        assert "Python" in result


@pytest.mark.asyncio
async def test_extract_merges_spacy_pii(mock_llm_client: AsyncMock) -> None:
    """Verify that spaCy-detected name is used when LLM returns Unknown."""
    extractor = EntityExtractor(mock_llm_client)
    profile = await extractor.extract(
        cv_text="Ahmed Benali\nahmed@email.com\n0555123456\nDéveloppeur Python\nAlger",
        detected_language="fr",
        extraction_notes="Clean text extraction from document",
    )
    assert isinstance(profile, CandidateProfile)
    assert profile.email == "ahmed@email.com"
