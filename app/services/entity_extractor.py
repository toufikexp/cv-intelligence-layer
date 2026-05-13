from __future__ import annotations

import re
from typing import Any

from app.models.schemas import CandidateProfile
from app.services.llm_client import LLMClient


_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "name": {"type": "STRING"},
        "email": {"type": "STRING", "nullable": True},
        "phone": {"type": "STRING", "nullable": True},
        "location": {"type": "STRING", "nullable": True},
        "current_title": {"type": "STRING", "nullable": True},
        "summary": {"type": "STRING", "nullable": True},
        "linkedin_url": {"type": "STRING", "nullable": True},
        "github_url": {"type": "STRING", "nullable": True},
        "portfolio_url": {"type": "STRING", "nullable": True},
        "skills": {"type": "ARRAY", "items": {"type": "STRING"}},
        "experience": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "company": {"type": "STRING"},
                    "role": {"type": "STRING"},
                    "start_date": {"type": "STRING", "nullable": True},
                    "end_date": {"type": "STRING", "nullable": True},
                    "description": {"type": "STRING", "nullable": True},
                    "location": {"type": "STRING", "nullable": True},
                },
                "required": ["company", "role"],
            },
        },
        "education": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "institution": {"type": "STRING"},
                    "degree": {"type": "STRING", "nullable": True},
                    "field": {"type": "STRING", "nullable": True},
                    "year": {"type": "STRING", "nullable": True},
                },
                "required": ["institution"],
            },
        },
        "languages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "language": {"type": "STRING"},
                    "level": {
                        "type": "STRING",
                        "enum": ["native", "fluent", "advanced", "intermediate", "beginner"],
                    },
                },
                "required": ["language", "level"],
            },
        },
        "certifications": {"type": "ARRAY", "items": {"type": "STRING"}},
        "achievements": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "year": {"type": "STRING", "nullable": True},
                    "description": {"type": "STRING", "nullable": True},
                },
                "required": ["title"],
            },
        },
        "total_experience_years": {"type": "NUMBER", "nullable": True},
    },
    "required": ["name"],
}

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
_URL_RE = re.compile(r"https?://[^\s)]+")


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(0).strip() if m else None


def _normalize_phone(raw: str) -> str:
    """Normalize phone numbers to international format.

    Patterns:
        Algerian: 05XX XXX XXX → +213 5XX XXX XXX
        French:   06 XX XX XX XX → +33 6 XX XX XX XX
        International: already has + prefix → keep as-is
    """
    digits = re.sub(r"[^\d+]", "", raw)
    # Already international
    if digits.startswith("+"):
        return raw.strip()
    # Algerian mobile: 05/06/07 followed by 8 digits
    if re.match(r"^0[567]\d{8}$", digits):
        return f"+213 {digits[1:4]} {digits[4:7]} {digits[7:]}"
    # French mobile: 06/07 followed by 8 digits
    if re.match(r"^0[67]\d{8}$", digits):
        return f"+33 {digits[1]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:]}"
    return raw.strip()


def _extract_urls(text: str) -> dict[str, str | None]:
    urls = _URL_RE.findall(text)
    linkedin = next((u for u in urls if "linkedin.com" in u.lower()), None)
    github = next((u for u in urls if "github.com" in u.lower()), None)
    portfolio = next((u for u in urls if u not in {linkedin, github}), None)
    return {"linkedin_url": linkedin, "github_url": github, "portfolio_url": portfolio}


def _normalize_llm_output(data: dict[str, Any]) -> dict[str, Any]:
    """Map common Gemini output variations to the canonical CandidateProfile shape.

    Gemini doesn't always honor the prompt schema strictly. This function
    defensively handles the most common variations so downstream Pydantic
    validation succeeds.
    """
    # 1. Flatten contact_info if nested
    contact = data.pop("contact_info", None) or {}
    if isinstance(contact, dict):
        for key in ("name", "email", "phone", "location", "linkedin_url", "github_url", "portfolio_url"):
            if contact.get(key) and not data.get(key):
                data[key] = contact[key]

    # 1b. Coerce name: accept dict {first_name, last_name} or {given, family}
    name = data.get("name")
    if isinstance(name, dict):
        parts = [
            str(name.get("first_name") or name.get("given") or name.get("firstName") or "").strip(),
            str(name.get("middle_name") or name.get("middle") or "").strip(),
            str(name.get("last_name") or name.get("family") or name.get("lastName") or "").strip(),
        ]
        full = " ".join(p for p in parts if p)
        data["name"] = full or name.get("full_name") or name.get("name") or ""
    elif name is not None and not isinstance(name, str):
        data["name"] = str(name)

    # 2. Flatten skills if dict-of-lists (Gemini often groups by category)
    skills = data.get("skills")
    if isinstance(skills, dict):
        flat: list[str] = []
        for v in skills.values():
            if isinstance(v, list):
                flat.extend(str(s).strip() for s in v if s)
            elif isinstance(v, str) and v.strip():
                flat.append(v.strip())
        data["skills"] = flat
    elif isinstance(skills, list):
        data["skills"] = [str(s).strip() for s in skills if s]
    elif skills is None:
        data["skills"] = []

    # 3. Normalize each experience entry
    experience = data.get("experience") or []
    if isinstance(experience, list):
        for exp in experience:
            if not isinstance(exp, dict):
                continue
            if "role" not in exp and "title" in exp:
                exp["role"] = exp.pop("title")
            if "role" not in exp and "position" in exp:
                exp["role"] = exp.pop("position")
            if "company" not in exp and "employer" in exp:
                exp["company"] = exp.pop("employer")
            desc = exp.get("description")
            if isinstance(desc, list):
                exp["description"] = "\n".join(str(d).strip() for d in desc if d)
            elif isinstance(desc, dict):
                exp["description"] = "\n".join(f"{k}: {v}" for k, v in desc.items() if v)

    # 4. Normalize education entries
    education = data.get("education") or []
    if isinstance(education, list):
        for edu in education:
            if not isinstance(edu, dict):
                continue
            if "field" not in edu and "field_of_study" in edu:
                edu["field"] = edu.pop("field_of_study")
            if "institution" not in edu and "school" in edu:
                edu["institution"] = edu.pop("school")
            if "institution" not in edu and "university" in edu:
                edu["institution"] = edu.pop("university")

    # 5. Normalize languages: accept list[str] or list[dict] with varying keys
    languages = data.get("languages") or []
    if isinstance(languages, list):
        normalized_langs: list[dict[str, str]] = []
        level_map = {
            "native": "native", "maternelle": "native", "natif": "native",
            "fluent": "fluent", "courant": "fluent", "bilingue": "fluent",
            "advanced": "advanced", "avance": "advanced", "avancé": "advanced",
            "intermediate": "intermediate", "intermediaire": "intermediate", "intermédiaire": "intermediate",
            "beginner": "beginner", "debutant": "beginner", "débutant": "beginner", "basic": "beginner",
        }
        for lang in languages:
            if isinstance(lang, str):
                # "Anglais (Courant)" or "English - Fluent"
                import re as _re
                m = _re.match(r"^([^(\-–]+)[\s(\-–]+([^)]+)\)?$", lang.strip())
                if m:
                    name = m.group(1).strip()
                    level_raw = m.group(2).strip().lower()
                    level = level_map.get(level_raw, "intermediate")
                    normalized_langs.append({"language": name, "level": level})
                else:
                    normalized_langs.append({"language": lang.strip(), "level": "intermediate"})
            elif isinstance(lang, dict):
                name = lang.get("language") or lang.get("name") or ""
                level_raw = str(lang.get("level") or lang.get("proficiency") or "intermediate").strip().lower()
                level = level_map.get(level_raw, "intermediate") if level_raw not in level_map.values() else level_raw
                if name:
                    normalized_langs.append({"language": str(name), "level": level})
        data["languages"] = normalized_langs

    # 6. Certifications: coerce list[dict] to list[str]
    certs = data.get("certifications") or []
    if isinstance(certs, list):
        flat_certs: list[str] = []
        for c in certs:
            if isinstance(c, str) and c.strip():
                flat_certs.append(c.strip())
            elif isinstance(c, dict):
                label = c.get("name") or c.get("title") or c.get("certification")
                if label:
                    flat_certs.append(str(label))
        data["certifications"] = flat_certs

    # 6b. Achievements: accept list[str] or list[dict] with varying keys
    achievements = data.get("achievements") or []
    if isinstance(achievements, list):
        normalized_ach: list[dict[str, str | None]] = []
        for item in achievements:
            if isinstance(item, str) and item.strip():
                normalized_ach.append({"title": item.strip(), "year": None, "description": None})
            elif isinstance(item, dict):
                title = item.get("title") or item.get("name") or item.get("project") or item.get("realization")
                if not title:
                    continue
                year = item.get("year") or item.get("date") or item.get("when")
                desc = item.get("description") or item.get("details") or item.get("summary")
                if isinstance(desc, list):
                    desc = "\n".join(str(d).strip() for d in desc if d)
                normalized_ach.append(
                    {
                        "title": str(title).strip(),
                        "year": str(year).strip() if year is not None else None,
                        "description": str(desc).strip() if desc else None,
                    }
                )
        data["achievements"] = normalized_ach
    else:
        data["achievements"] = []

    # 7. Ensure name exists (Pydantic requires it)
    if not data.get("name"):
        data["name"] = "Unknown"

    return data


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
            response_schema=_EXTRACTION_SCHEMA,
            variables={
                "detected_language": detected_language,
                "extraction_notes": extraction_notes,
                "cv_text": cv_text[:30000],
            },
        )

        # Defensive normalization of Gemini output variations
        data = _normalize_llm_output(data)

        # Prefer deterministic regex values when present
        if regex_email:
            data["email"] = regex_email
        if regex_phone and not data.get("phone"):
            data["phone"] = _normalize_phone(regex_phone)
        if data.get("phone"):
            data["phone"] = _normalize_phone(data["phone"])
        for k, v in urls.items():
            if v and not data.get(k):
                data[k] = v

        return CandidateProfile.model_validate(data, strict=False)

