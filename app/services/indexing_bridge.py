from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.schemas import CandidateProfile


@dataclass(frozen=True)
class SearchDocument:
    external_id: str
    content: str
    metadata: dict[str, Any]


def build_search_document(*, file_hash: str, profile: CandidateProfile, language: str | None) -> SearchDocument:
    """Transform a CandidateProfile into a Semantic Search document."""

    skills = profile.skills or []
    exp = profile.experience or []
    edu = profile.education or []

    exp_summary = ", ".join(f"{e.role} at {e.company}" for e in exp[:6] if e.role and e.company)
    edu_summary = ", ".join(
        " ".join([p for p in [e.degree, e.institution] if p]) for e in edu[:3] if e.institution
    )

    content = "\n".join(
        [
            f"{profile.current_title or ''} | {profile.name}".strip(" |"),
            f"Skills: {', '.join(skills)}" if skills else "Skills:",
            f"Experience: {exp_summary}" if exp_summary else "Experience:",
            f"Education: {edu_summary}" if edu_summary else "Education:",
            profile.summary or "",
        ]
    ).strip()

    metadata: dict[str, Any] = {
        "skills": skills,
        "experience_years": int(profile.total_experience_years or 0),
        "language": language or "mixed",
        "location": profile.location,
        "education_level": (edu[0].degree.lower() if edu and edu[0].degree else None),
    }
    return SearchDocument(external_id=file_hash, content=content, metadata={k: v for k, v in metadata.items() if v is not None})

