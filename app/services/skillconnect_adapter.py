from __future__ import annotations

from typing import Any

from app.models.schemas import (
    AchievementEntry,
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
)
from app.services.catalog_matcher import CatalogMatcher


def to_internal(
    payload: dict[str, Any],
    catalogs: CatalogMatcher,
) -> tuple[CandidateProfile, dict[str, Any]]:
    """Convert a SkillConnect sync payload into internal CandidateProfile + external_metadata.

    The CandidateProfile gets names (not codes) so search/ranking work.
    external_metadata stores the full codified payload for lossless round-trip.
    """
    employee = payload.get("employee") or {}
    name = f"{employee.get('firstName', '')} {employee.get('lastName', '')}".strip() or "Unknown"

    skills_raw = payload.get("skills") or []
    skill_names: list[str] = []
    for s in skills_raw:
        code = s.get("skill") if isinstance(s, dict) else s
        resolved = catalogs.skill_name(code) if code else None
        if resolved:
            skill_names.append(resolved)
        elif isinstance(s, dict) and s.get("name"):
            skill_names.append(s["name"])

    experiences: list[ExperienceEntry] = []
    for exp in payload.get("experiences") or []:
        experiences.append(ExperienceEntry(
            company=exp.get("company") or exp.get("establishment") or "Unknown",
            role=exp.get("title") or exp.get("role") or "Unknown",
            start_date=exp.get("startDate"),
            end_date=exp.get("endDate"),
            description=exp.get("description"),
            location=exp.get("location"),
        ))

    educations: list[EducationEntry] = []
    for edu in payload.get("educations") or []:
        institution_code = edu.get("establishment")
        institution_name = catalogs.establishment_name(institution_code) if institution_code else None
        educations.append(EducationEntry(
            institution=institution_name or edu.get("establishmentName") or institution_code or "Unknown",
            degree=edu.get("degree"),
            field=edu.get("field") or edu.get("speciality"),
            year=edu.get("year") or edu.get("endDate"),
        ))

    languages: list[LanguageEntry] = []
    proficiency_map = {
        "native": "native",
        "fluent": "fluent",
        "advanced": "advanced",
        "intermediate": "intermediate",
        "beginner": "beginner",
        "basic": "beginner",
        "professional": "fluent",
    }
    for lang in payload.get("languages") or []:
        lang_code = lang.get("language") if isinstance(lang, dict) else lang
        lang_name = catalogs.language_name(lang_code) if lang_code else None
        if not lang_name and isinstance(lang, dict):
            lang_name = lang.get("name") or lang_code
        if lang_name:
            raw_prof = str(lang.get("proficiency", "intermediate") if isinstance(lang, dict) else "intermediate").lower()
            level = proficiency_map.get(raw_prof, "intermediate")
            languages.append(LanguageEntry(language=lang_name, level=level))

    certifications: list[str] = []
    for cert in payload.get("certifications") or []:
        if isinstance(cert, dict):
            title = cert.get("title") or cert.get("name") or ""
            issuer = cert.get("issuer") or ""
            label = f"{title} — {issuer}".strip(" —") if issuer else title
            if label:
                certifications.append(label)
        elif isinstance(cert, str) and cert.strip():
            certifications.append(cert.strip())

    achievements: list[AchievementEntry] = []
    for ach in payload.get("achievements") or []:
        if isinstance(ach, dict):
            title = ach.get("title") or ach.get("name") or ""
            if title:
                achievements.append(AchievementEntry(
                    title=title,
                    year=ach.get("year") or ach.get("startDate"),
                    description=ach.get("description"),
                ))

    profile = CandidateProfile(
        name=name,
        email=employee.get("email"),
        phone=employee.get("phone"),
        location=employee.get("location") or payload.get("location"),
        current_title=employee.get("currentTitle") or payload.get("currentTitle"),
        summary=payload.get("summary"),
        skills=skill_names,
        experience=experiences,
        education=educations,
        languages=languages,
        certifications=certifications,
        achievements=achievements,
        total_experience_years=payload.get("totalExperienceYears"),
    )

    external_metadata: dict[str, Any] = {
        "employee": employee,
        "skills_coded": skills_raw,
        "educations_coded": payload.get("educations") or [],
        "languages_coded": payload.get("languages") or [],
        "certifications_coded": payload.get("certifications") or [],
        "tags": payload.get("tags") or [],
        "visible": payload.get("visible", True),
        "photoPath": payload.get("photoPath"),
        "cvPath": payload.get("cvPath"),
        "rating": payload.get("rating"),
    }

    return profile, external_metadata


def to_skillconnect(
    profile: CandidateProfile,
    external_metadata: dict[str, Any] | None,
    catalogs: CatalogMatcher,
    competencies: list[str] | None = None,
) -> dict[str, Any]:
    """Convert internal CandidateProfile + external_metadata back to SkillConnect shape.

    Used for extract responses and GET endpoints. Codes are resolved from names
    via the catalog; unmatched skills get code=null.
    """
    ext = external_metadata or {}

    skills_out: list[dict[str, Any]] = []
    if ext.get("skills_coded"):
        skills_out = ext["skills_coded"]
    else:
        matched_names = set(competencies or [])
        for skill_name in profile.skills:
            code = catalogs.skill_code(skill_name)
            skills_out.append({
                "skill": code,
                "name": skill_name,
                "score": None,
            })
        for comp_name in (competencies or []):
            if comp_name not in [s.get("name") for s in skills_out]:
                code = catalogs.skill_code(comp_name)
                skills_out.append({
                    "skill": code,
                    "name": comp_name,
                    "score": None,
                })

    educations_out: list[dict[str, Any]] = []
    if ext.get("educations_coded"):
        educations_out = ext["educations_coded"]
    else:
        for edu in profile.education:
            est_code = catalogs.establishment_code(edu.institution)
            educations_out.append({
                "establishment": est_code,
                "establishmentName": edu.institution,
                "degree": edu.degree,
                "field": edu.field,
                "year": edu.year,
            })

    languages_out: list[dict[str, Any]] = []
    if ext.get("languages_coded"):
        languages_out = ext["languages_coded"]
    else:
        level_to_proficiency = {
            "native": "native",
            "fluent": "fluent",
            "advanced": "advanced",
            "intermediate": "intermediate",
            "beginner": "beginner",
        }
        for lang in profile.languages:
            lang_code = catalogs.language_code(lang.language)
            languages_out.append({
                "language": lang_code,
                "name": lang.language,
                "proficiency": level_to_proficiency.get(lang.level, "intermediate"),
            })

    certifications_out: list[dict[str, Any]] = []
    if ext.get("certifications_coded"):
        certifications_out = ext["certifications_coded"]
    else:
        for cert in profile.certifications:
            certifications_out.append({"title": cert})

    experiences_out: list[dict[str, Any]] = []
    for exp in profile.experience:
        experiences_out.append({
            "company": exp.company,
            "title": exp.role,
            "startDate": exp.start_date,
            "endDate": exp.end_date,
            "description": exp.description,
            "location": exp.location,
        })

    achievements_out: list[dict[str, Any]] = []
    for ach in profile.achievements:
        achievements_out.append({
            "title": ach.title,
            "year": ach.year,
            "description": ach.description,
        })

    employee = ext.get("employee") or {}
    if not employee and profile.name != "Unknown":
        parts = profile.name.rsplit(" ", 1)
        employee = {
            "firstName": parts[0] if len(parts) > 1 else profile.name,
            "lastName": parts[-1] if len(parts) > 1 else "",
            "email": profile.email,
            "phone": profile.phone,
            "location": profile.location,
            "currentTitle": profile.current_title,
        }

    result: dict[str, Any] = {
        "employee": employee,
        "currentTitle": profile.current_title,
        "summary": profile.summary,
        "location": profile.location,
        "skills": skills_out,
        "experiences": experiences_out,
        "educations": educations_out,
        "languages": languages_out,
        "certifications": certifications_out,
        "achievements": achievements_out,
        "totalExperienceYears": profile.total_experience_years,
        "tags": ext.get("tags") or [],
        "visible": ext.get("visible", True),
        "photoPath": ext.get("photoPath"),
        "cvPath": ext.get("cvPath"),
        "rating": ext.get("rating"),
    }
    return result
