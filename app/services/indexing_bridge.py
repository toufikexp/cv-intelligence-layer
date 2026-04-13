from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.schemas import CandidateProfile


@dataclass(frozen=True)
class SearchDocument:
    external_id: str
    content: str
    metadata: dict[str, Any]


def build_search_document(
    *,
    external_id: str,
    profile: CandidateProfile,
    raw_text: str,
    language: str | None,
) -> SearchDocument:
    """Transform a CandidateProfile + raw CV text into a Semantic Search document.

    Args:
        external_id: Caller-supplied stable document identifier.
        profile: Extracted CandidateProfile (used only for metadata derivation).
        raw_text: Raw CV text extracted by the document pipeline. This becomes
            the document ``content`` so semantic recall matches against the
            full CV body rather than a short formatted projection.
        language: Detected language code.
    """

    edu = profile.education or []

    content = (raw_text or "").strip()
    if not content:
        # Defensive: Semantic Search rejects empty content. Fall back to the
        # least-bad projection of the profile so the document is still
        # indexable even when text extraction produced nothing.
        content = (profile.summary or profile.name or "").strip()

    metadata: dict[str, Any] = {
        "skills": profile.skills or [],
        "experience_years": int(profile.total_experience_years or 0),
        "language": language or "mixed",
        "location": profile.location,
        "education_level": (edu[0].degree.lower() if edu and edu[0].degree else None),
    }
    return SearchDocument(
        external_id=external_id,
        content=content,
        metadata={k: v for k, v in metadata.items() if v is not None},
    )
