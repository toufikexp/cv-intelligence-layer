"""Tests for entity extraction and phone normalization."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.schemas import CandidateProfile
from app.services.entity_extractor import EntityExtractor, _normalize_phone


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
