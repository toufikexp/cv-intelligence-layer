from __future__ import annotations

import re
from typing import Any

from app.models.schemas import CandidateProfile
from app.services.llm_client import LLMClient


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
_URL_RE = re.compile(r"https?://[^\s)]+")


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(0).strip() if m else None


def _extract_urls(text: str) -> dict[str, str | None]:
    urls = _URL_RE.findall(text)
    linkedin = next((u for u in urls if "linkedin.com" in u.lower()), None)
    github = next((u for u in urls if "github.com" in u.lower()), None)
    portfolio = next((u for u in urls if u not in {linkedin, github}), None)
    return {"linkedin_url": linkedin, "github_url": github, "portfolio_url": portfolio}


class EntityExtractor:
    """Two-pass entity extraction: regex then LLM structured extraction."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def extract(self, *, cv_text: str, detected_language: str, extraction_notes: str) -> CandidateProfile:
        regex_email = _first_match(_EMAIL_RE, cv_text)
        regex_phone = _first_match(_PHONE_RE, cv_text)
        urls = _extract_urls(cv_text)

        data: dict[str, Any] = await self._llm.complete_json(
            prompt_key="cv_entity_extraction",
            variables={
                "detected_language": detected_language,
                "extraction_notes": extraction_notes,
                "cv_text": cv_text[:30000],
            },
        )

        # Prefer deterministic regex values when present
        if regex_email:
            data["email"] = regex_email
        if regex_phone and not data.get("phone"):
            data["phone"] = regex_phone
        for k, v in urls.items():
            if v and not data.get(k):
                data[k] = v

        return CandidateProfile.model_validate(data, strict=False)

