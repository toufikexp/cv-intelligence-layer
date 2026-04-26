from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.schemas import CandidateProfile


@dataclass(frozen=True)
class SearchDocument:
    external_id: str
    content: str
    metadata: dict[str, Any]


def build_synthetic_text(profile: CandidateProfile) -> str:
    """Build a plain-text representation of a CandidateProfile.

    Used by the JSON-create endpoint: the resulting text becomes both
    ``raw_text`` (stored on the CV row) and the Semantic Search document
    ``content`` (used for embedding / recall).
    """
    parts: list[str] = []

    if profile.name:
        parts.append(f"Name: {profile.name}")
    if profile.current_title:
        parts.append(f"Title: {profile.current_title}")
    if profile.location:
        parts.append(f"Location: {profile.location}")
    if profile.email:
        parts.append(f"Email: {profile.email}")
    if profile.phone:
        parts.append(f"Phone: {profile.phone}")

    if profile.summary:
        parts.append(f"\nSummary:\n{profile.summary}")

    if profile.skills:
        parts.append(f"\nSkills: {', '.join(profile.skills)}")

    if profile.experience:
        lines = ["Experience:"]
        for e in profile.experience:
            line = f"- {e.role} @ {e.company}"
            if e.start_date or e.end_date:
                line += f" ({e.start_date or ''} - {e.end_date or ''})"
            if e.description:
                line += f": {e.description}"
            lines.append(line)
        parts.append("\n" + "\n".join(lines))

    if profile.education:
        lines = ["Education:"]
        for e in profile.education:
            line = f"- {e.degree or ''} {e.field or ''} — {e.institution}"
            if e.year:
                line += f" ({e.year})"
            lines.append(line)
        parts.append("\n" + "\n".join(lines))

    if profile.languages:
        langs = ", ".join(f"{l.language} ({l.level})" for l in profile.languages)
        parts.append(f"\nLanguages: {langs}")

    if profile.certifications:
        parts.append(f"\nCertifications: {', '.join(profile.certifications)}")

    if profile.achievements:
        lines = ["Achievements:"]
        for a in profile.achievements:
            line = f"- {a.title}"
            if a.year:
                line += f" ({a.year})"
            if a.description:
                line += f": {a.description}"
            lines.append(line)
        parts.append("\n" + "\n".join(lines))

    return "\n".join(parts).strip()


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
