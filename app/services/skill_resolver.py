from __future__ import annotations

from typing import Any

from app.models.schemas import (
    AchievementEntry,
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
)
from app.services.catalog_store import CatalogStore

# CEFR (SkillConnect) <-> internal LanguageLevel. Internal levels are a coarse
# 5-point scale; map both ways without losing the verbatim CEFR (kept in the
# stored coded payload).
_CEFR_TO_LEVEL = {
    "NATIVE": "native",
    "C2": "fluent",
    "C1": "fluent",
    "B2": "advanced",
    "B1": "intermediate",
    "A2": "beginner",
    "A1": "beginner",
}
_LEVEL_TO_CEFR = {
    "native": "NATIVE",
    "fluent": "C1",
    "advanced": "B2",
    "intermediate": "B1",
    "beginner": "A1",
}


def _full_name(employee: dict[str, Any]) -> str:
    first = (employee.get("firstname") or employee.get("firstName") or "").strip()
    last = (employee.get("lastname") or employee.get("lastName") or "").strip()
    return f"{first} {last}".strip() or "Unknown"


def coded_payload_to_profile(payload: dict[str, Any], store: CatalogStore) -> CandidateProfile:
    """Build the internal names-only CandidateProfile from a SkillConnect payload.

    Skill codes are resolved to names via the catalog (unmatched codes are
    dropped from the engine view but remain in the stored coded payload).
    All other fields already arrive as free text.
    """
    employee = payload.get("employee") or {}

    skill_names: list[str] = []
    for s in payload.get("skills") or []:
        code = s.get("skill") if isinstance(s, dict) else s
        name = store.skill_name(code) if code else None
        if name:
            skill_names.append(name)

    experiences = [
        ExperienceEntry(
            company=e.get("company") or "Unknown",
            role=e.get("role") or "Unknown",
            start_date=e.get("startDate"),
            end_date=e.get("endDate"),
            description=e.get("description"),
        )
        for e in (payload.get("experiences") or [])
    ]

    educations = []
    for e in payload.get("educations") or []:
        estab_code = e.get("establishment")
        institution = e.get("institution") or (store.establishment_name(estab_code) if estab_code else None)
        educations.append(
            EducationEntry(
                institution=institution or "Unknown",
                degree=e.get("typeEducation"),
                field=e.get("fieldOfStudy"),
                year=e.get("dateGraduation"),
            )
        )

    languages = []
    for lg in payload.get("languages") or []:
        name = lg.get("language") if isinstance(lg, dict) else lg
        if not name:
            continue
        cefr = str((lg.get("proficiency") if isinstance(lg, dict) else "") or "").upper()
        languages.append(LanguageEntry(language=name, level=_CEFR_TO_LEVEL.get(cefr, "intermediate")))

    certifications = []
    for c in payload.get("certifications") or []:
        if isinstance(c, dict):
            title = c.get("title") or ""
            issuer = c.get("issuer") or ""
            label = f"{title} — {issuer}".strip(" —") if issuer else title
            if label:
                certifications.append(label)
        elif isinstance(c, str) and c.strip():
            certifications.append(c.strip())

    achievements = [
        AchievementEntry(
            title=a.get("title") or "",
            year=(a.get("startDate") or "")[:4] or None,
            description=a.get("description"),
        )
        for a in (payload.get("achievements") or [])
        if isinstance(a, dict) and a.get("title")
    ]

    return CandidateProfile(
        name=_full_name(employee),
        email=employee.get("email"),
        current_title=employee.get("function") or employee.get("currentTitle"),
        summary=payload.get("summary"),
        skills=skill_names,
        experience=experiences,
        education=educations,
        languages=languages,
        certifications=certifications,
        achievements=achievements,
    )


def profile_to_coded_projection(profile: CandidateProfile, store: CatalogStore) -> dict[str, Any]:
    """Build the SkillConnect-coded projection for the extract response.

    Skills/establishments/languages are matched to codes; unmatched → ``null``
    code (never fabricated), keeping the readable name alongside.
    """
    skills = [
        {"skill": store.skill_code(s), "name": s}
        for s in profile.skills
    ]
    educations = []
    for e in profile.education:
        educations.append(
            {
                "institution": e.institution,
                "establishment": store.establishment_code(e.institution),
                "fieldOfStudy": e.field,
                "typeEducation": e.degree,
                "dateGraduation": e.year,
            }
        )
    languages = [
        {
            "language": lg.language,
            "languageCode": store.language_code(lg.language),
            "proficiency": _LEVEL_TO_CEFR.get(lg.level, "B1"),
        }
        for lg in profile.languages
    ]
    experiences = [
        {
            "role": e.role,
            "company": e.company,
            "startDate": e.start_date,
            "endDate": e.end_date,
            "description": e.description,
        }
        for e in profile.experience
    ]
    achievements = [
        {"title": a.title, "description": a.description, "startDate": a.year}
        for a in profile.achievements
    ]
    return {
        "skills": skills,
        "experiences": experiences,
        "educations": educations,
        "languages": languages,
        "certifications": list(profile.certifications),
        "achievements": achievements,
    }
