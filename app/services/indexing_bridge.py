from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.models.schemas import CandidateProfile
from app.services.catalog_store import catalog_store


@dataclass(frozen=True)
class SearchDocument:
    external_id: str
    content: str
    metadata: dict[str, Any]


def _skill_names(profile: CandidateProfile) -> list[str]:
    """Resolve catalog skill codes to their human-readable names.

    Semantic Search receives NAMES, never codes. Skills are stored as codes
    (``skill``); we look up the canonical name from the catalog at index time.
    Unresolved codes are dropped rather than leaking a code into Search.
    """
    names: list[str] = []
    for s in profile.skills:
        if not s.skill:
            continue
        name = catalog_store.skill_name(s.skill)
        if name:
            names.append(name)
    return names


def _establishment_label(establishment: str | None) -> str:
    """Human-readable school name for Semantic Search (never the code).

    ``establishment`` is either a catalog code (resolved profiles) or a raw
    school name (extract API tolerance). Returns the readable name in both
    cases.
    """
    if not establishment:
        return ""
    name = catalog_store.establishment_name(establishment)
    if name:
        return name
    return establishment


def _estimate_experience_years(profile: CandidateProfile) -> int:
    """Derive total experience years from experiences date spans."""
    total_months = 0
    for e in profile.experiences:
        start = e.startDate
        end = e.endDate
        if not start:
            continue
        try:
            sy = int(start[:4])
            sm = int(start[5:7]) if len(start) >= 7 else 1
        except (ValueError, IndexError):
            continue
        if end and end.lower() != "present":
            try:
                ey = int(end[:4])
                em = int(end[5:7]) if len(end) >= 7 else 12
            except (ValueError, IndexError):
                ey, em = date.today().year, date.today().month
        else:
            ey, em = date.today().year, date.today().month
        months = (ey - sy) * 12 + (em - sm)
        if months > 0:
            total_months += months
    return max(total_months // 12, 0)


def build_synthetic_text(profile: CandidateProfile) -> str:
    """Build a plain-text representation of a CandidateProfile.

    Used by the JSON-create endpoint: the resulting text becomes both
    ``raw_text`` (stored on the CV row) and the Semantic Search document
    ``content`` (used for embedding / recall).
    """
    parts: list[str] = []

    emp = profile.employee
    if emp:
        name = f"{emp.firstname or ''} {emp.lastname or ''}".strip()
        if name:
            parts.append(f"Name: {name}")
        if emp.function:
            parts.append(f"Title: {emp.function}")
        if emp.region:
            parts.append(f"Location: {emp.region}")
        if emp.email:
            parts.append(f"Email: {emp.email}")
        if emp.phone:
            parts.append(f"Phone: {emp.phone}")

    if profile.summary:
        parts.append(f"\nSummary:\n{profile.summary}")

    skill_names = _skill_names(profile)
    if skill_names:
        parts.append(f"\nSkills: {', '.join(skill_names)}")

    if profile.experiences:
        lines = ["Experience:"]
        for e in profile.experiences:
            line = f"- {e.role or ''} @ {e.company or ''}"
            if e.startDate or e.endDate:
                line += f" ({e.startDate or ''} - {e.endDate or ''})"
            if e.description:
                line += f": {e.description}"
            lines.append(line)
        parts.append("\n" + "\n".join(lines))

    if profile.educations:
        lines = ["Education:"]
        for e in profile.educations:
            school = _establishment_label(e.establishment)
            line = f"- {e.typeEducation or ''} {e.fieldOfStudy or ''} — {school}"
            if e.dateGraduation:
                line += f" ({e.dateGraduation})"
            lines.append(line)
        parts.append("\n" + "\n".join(lines))

    if profile.languages:
        langs = ", ".join(
            f"{lg.language or ''} ({lg.proficiency or ''})" for lg in profile.languages
        )
        parts.append(f"\nLanguages: {langs}")

    cert_titles = [c.title for c in profile.certifications if c.title]
    if cert_titles:
        parts.append(f"\nCertifications: {', '.join(cert_titles)}")

    if profile.achievements:
        lines = ["Achievements:"]
        for a in profile.achievements:
            line = f"- {a.title or ''}"
            if a.startDate:
                line += f" ({a.startDate})"
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

    SS gets NAMES and text only — never codes.
    """
    content = (raw_text or "").strip()
    if not content:
        content = (profile.summary or "").strip()
        if not content and profile.employee:
            name = f"{profile.employee.firstname or ''} {profile.employee.lastname or ''}".strip()
            content = name or ""

    skill_names = _skill_names(profile)
    experience_years = _estimate_experience_years(profile)

    edu = profile.educations
    edu_level = edu[0].typeEducation.lower() if edu and edu[0].typeEducation else None

    location = None
    if profile.employee:
        location = profile.employee.workingSite or profile.employee.region

    metadata: dict[str, Any] = {
        "skills": skill_names,
        "experience_years": experience_years,
        "language": language or "mixed",
        "location": location,
        "education_level": edu_level,
    }
    return SearchDocument(
        external_id=external_id,
        content=content,
        metadata={k: v for k, v in metadata.items() if v is not None},
    )
