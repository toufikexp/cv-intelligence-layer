from __future__ import annotations

import logging
import re
import time
from typing import Any

import spacy

from app.models.schemas import CandidateProfile, EmployeeInfo
from app.services.llm_client import LLMClient
from app.utils.metrics import entity_extraction_duration_seconds

logger = logging.getLogger("cv_layer.entity_extractor")

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
_URL_RE = re.compile(r"https?://[^\s)]+")

_DOB_AGE_RE = re.compile(
    r"(?:"
    r"(?:Né|Née|Born|Date de naissance|D\.?N\.?|DOB|Birthdate|Date of birth)"
    r"\s*[:;]?\s*(?:le\s+|the\s+|on\s+|du\s+)?[\d/.\- ]{6,12}"
    r"|"
    r"(?:Age|Âge)\s*[:;]?\s*\d{1,3}\s*(?:ans|years?\s*old?)?"
    r"|"
    r"\b\d{1,3}\s+ans\b"
    r"|"
    r"\b\d{1,3}\s+years?\s+old\b"
    r")",
    re.IGNORECASE,
)

_DOB_KEYWORDS_RE = re.compile(
    r"(?:Né|Née|Born|Date de naissance|D\.?N\.?|DOB|Birthdate|"
    r"Date of birth|Age|Âge)\b",
    re.IGNORECASE,
)

_CONTACT_BLOCK_CAP = 8
_HEADER_ZONE_CAP = 8
_PROSE_LINE_LEN = 80
_HEADER_NAME_SCAN_LINES = 12

_SECTION_HEADER_WORDS = {
    "profil", "profile", "profil professionnel", "professional profile",
    "professional summary", "summary", "résumé", "resume", "objectif",
    "objective", "à propos", "about", "expérience", "expériences",
    "experience", "experiences", "work experience", "professional experience",
    "formation", "education", "études", "etudes", "compétences",
    "competences", "skills", "technical skills", "langues", "languages",
    "certifications", "certification", "projets", "projects", "contact",
    "centres d'intérêt", "interests", "références", "references",
    "réalisations", "achievements",
}

_SECTION_KEYWORDS = {
    "experience", "experiences", "expérience", "expériences", "formation",
    "formations", "education", "etudes", "études", "compétences", "competences",
    "skills", "langues", "languages", "profil", "profile", "summary", "résumé",
    "certifications", "projets", "projects", "contact", "references", "références",
    "objectif", "objective", "aptitudes", "réalisations", "achievements",
    "diplômes", "diplomes", "parcours", "stages", "professionnelles",
    "professionnels", "professionnel", "professionnelle",
}

_YEAR_RANGE_RE = re.compile(r"^(?:19|20)\d{2}(?:\s*[-–/]\s*(?:19|20)\d{2})+$")

_PII_LABEL_WORDS = {
    "adresse", "address", "email", "e-mail", "mail", "courriel", "tel",
    "tél", "téléphone", "telephone", "phone", "mobile", "gsm", "fax",
    "contact", "nationalité", "nationality", "linkedin", "github",
}

_NAME_LINE_RE = re.compile(r"^[A-Za-zÀ-ÿ' .\-]{2,40}$")

_spacy_models: dict[str, spacy.Language] = {}


def load_spacy_models() -> None:
    _spacy_models["fr"] = spacy.load("fr_core_news_sm")
    _spacy_models["en"] = spacy.load("en_core_web_sm")
    logger.info("spaCy NER models loaded (fr + en)")


def _get_spacy_model(lang: str) -> spacy.Language:
    key = "fr" if lang.startswith("fr") else "en"
    return _spacy_models[key]


def _is_section_header(line: str) -> bool:
    s = line.strip().rstrip(":").strip().lower()
    if not s:
        return False
    if s in _SECTION_HEADER_WORDS:
        return True
    if len(s) <= 45 and set(re.findall(r"[a-zà-ÿ]+", s)) & _SECTION_KEYWORDS:
        return True
    return False


def _contact_block(text: str) -> str:
    block: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        if _is_section_header(line) or len(line.strip()) > _PROSE_LINE_LEN:
            break
        block.append(line)
        if len(block) >= _CONTACT_BLOCK_CAP:
            break
    return "\n".join(block)


def _looks_like_name(line: str) -> bool:
    s = line.strip()
    if "\n" in s:
        return False
    if not s[:1].isupper() or not _NAME_LINE_RE.match(s):
        return False
    tokens = s.split()
    if not 1 < len(tokens) <= 4:
        return False
    if s.rstrip(":").lower() in _SECTION_HEADER_WORDS:
        return False
    if set(re.findall(r"[a-zà-ÿ]+", s.lower())) & _SECTION_KEYWORDS:
        return False
    return not any(t.lower() in _PII_LABEL_WORDS for t in tokens)


def _extract_pii_entities(text: str, language: str) -> dict[str, Any]:
    block = _contact_block(text)

    nlp = _get_spacy_model(language)
    doc = nlp(block)

    persons = [e.text for e in doc.ents if e.label_ in ("PER", "PERSON")]
    locations = [
        e.text
        for e in doc.ents
        if e.label_ in ("LOC", "GPE")
        and e.text.strip().lower() not in _PII_LABEL_WORDS
    ]

    dob = None
    for ent in doc.ents:
        if ent.label_ == "DATE":
            context = block[max(0, ent.start_char - 40) : ent.end_char]
            if _DOB_KEYWORDS_RE.search(context):
                dob = ent.text
                break

    name = persons[0] if persons else None
    if not name:
        name = next(
            (line.strip() for line in block.split("\n") if _looks_like_name(line)),
            None,
        )
    if not name:
        header_zone: list[str] = []
        for line in text.split("\n"):
            if not line.strip():
                continue
            if _is_section_header(line):
                break
            header_zone.append(line)
            if len(header_zone) >= _HEADER_NAME_SCAN_LINES:
                break
        name = next((ln.strip() for ln in header_zone if _looks_like_name(ln)), None)

    location = locations[0] if locations else None

    person_terms = list(dict.fromkeys(([name] if name else []) + persons))
    location_terms = list(dict.fromkeys(locations))

    return {
        "name": name,
        "location": location,
        "dob": dob,
        "person_terms": person_terms,
        "location_terms": location_terms,
    }


def _redact_pii(
    text: str,
    person_terms: list[str],
    location_terms: list[str],
    dob: str | None,
) -> str:
    out = text
    for term in person_terms:
        if term and len(term.strip()) >= 2:
            out = out.replace(term, "[REDACTED_NAME]")
    for term in location_terms:
        if term and len(term.strip()) >= 2:
            out = out.replace(term, "[REDACTED_LOCATION]")
    if dob:
        out = out.replace(dob, "[REDACTED_DOB]")
    out = _EMAIL_RE.sub("[REDACTED_EMAIL]", out)
    out = _redact_phones(out)
    out = _URL_RE.sub("[REDACTED_URL]", out)
    out = _DOB_AGE_RE.sub("[REDACTED_DOB]", out)
    return out


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(0).strip() if m else None


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+"):
        return raw.strip()
    if re.match(r"^0[567]\d{8}$", digits):
        return f"+213 {digits[1:4]} {digits[4:7]} {digits[7:]}"
    if re.match(r"^0[67]\d{8}$", digits):
        return f"+33 {digits[1]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:]}"
    return raw.strip()


def _extract_phone(text: str) -> str | None:
    for m in _PHONE_RE.finditer(text):
        cand = m.group(0).strip()
        digits = re.sub(r"\D", "", cand)
        if 9 <= len(digits) <= 15 and not _YEAR_RANGE_RE.match(cand):
            return cand
    return None


def _redact_phones(text: str) -> str:
    def _repl(m: re.Match[str]) -> str:
        cand = m.group(0).strip()
        digits = re.sub(r"\D", "", cand)
        if 9 <= len(digits) <= 15 and not _YEAR_RANGE_RE.match(cand):
            return "[REDACTED_PHONE]"
        return m.group(0)
    return _PHONE_RE.sub(_repl, text)


def _strip_header_zone(text: str) -> str:
    lines = text.split("\n")
    cut = 0
    seen = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        seen += 1
        if _is_section_header(line):
            cut = i
            break
        if seen >= _HEADER_ZONE_CAP:
            cut = i + 1
            break
    if cut == 0:
        return text
    return "[CONTACT_DETAILS_REDACTED]\n" + "\n".join(lines[cut:])


def usable_char_count(text: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ÿ0-9]", text))


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return full_name.strip(), ""


def _normalize_llm_output(data: dict[str, Any]) -> dict[str, Any]:
    """Map common Gemini output variations to the new SkillConnect shape."""
    # skills: accept dict-of-lists, list of strings, or list of dicts
    skills = data.get("skills")
    if isinstance(skills, dict):
        flat: list[dict[str, Any]] = []
        for v in skills.values():
            if isinstance(v, list):
                for s in v:
                    if isinstance(s, str) and s.strip():
                        flat.append({"skill": s.strip(), "score": None})
                    elif isinstance(s, dict):
                        if "skill" not in s and "name" in s:
                            s["skill"] = s.pop("name")
                        flat.append(s)
        data["skills"] = flat
    elif isinstance(skills, list):
        normalized_skills: list[dict[str, Any]] = []
        for s in skills:
            if isinstance(s, str) and s.strip():
                normalized_skills.append({"skill": s.strip(), "score": None})
            elif isinstance(s, dict):
                if "skill" not in s and "name" in s:
                    s["skill"] = s.pop("name")
                normalized_skills.append(s)
        data["skills"] = normalized_skills
    elif skills is None:
        data["skills"] = []

    # experiences: normalize field name aliases
    exp_key = "experiences" if "experiences" in data else "experience"
    experiences = data.pop(exp_key, None) or []
    if isinstance(experiences, list):
        normalized_exp: list[dict[str, Any]] = []
        for exp in experiences:
            if not isinstance(exp, dict):
                continue
            if "role" not in exp and "title" in exp:
                exp["role"] = exp.pop("title")
            if "role" not in exp and "position" in exp:
                exp["role"] = exp.pop("position")
            if "company" not in exp and "employer" in exp:
                exp["company"] = exp.pop("employer")
            if "startDate" not in exp and "start_date" in exp:
                exp["startDate"] = exp.pop("start_date")
            if "endDate" not in exp and "end_date" in exp:
                exp["endDate"] = exp.pop("end_date")
            desc = exp.get("description")
            if isinstance(desc, list):
                exp["description"] = "\n".join(str(d).strip() for d in desc if d)
            elif isinstance(desc, dict):
                exp["description"] = "\n".join(f"{k}: {v}" for k, v in desc.items() if v)
            normalized_exp.append(exp)
        data["experiences"] = normalized_exp
    else:
        data["experiences"] = []

    # educations: normalize field name aliases
    edu_key = "educations" if "educations" in data else "education"
    educations = data.pop(edu_key, None) or []
    if isinstance(educations, list):
        normalized_edu: list[dict[str, Any]] = []
        for edu in educations:
            if not isinstance(edu, dict):
                continue
            # institution = free-text school name (kept as written on the CV);
            # establishment = catalog CODE, resolved later by enrich_profile.
            if not edu.get("institution"):
                edu["institution"] = (
                    edu.pop("school", None)
                    or edu.pop("university", None)
                    # Gemini may put the name in 'establishment'; treat it as the
                    # free-text name — enrich_profile resolves the code from it.
                    or edu.pop("establishment", None)
                    or ""
                )
            edu.pop("establishment", None)
            if "fieldOfStudy" not in edu and "field_of_study" in edu:
                edu["fieldOfStudy"] = edu.pop("field_of_study")
            if "fieldOfStudy" not in edu and "field" in edu:
                edu["fieldOfStudy"] = edu.pop("field")
            if "typeEducation" not in edu and "degree" in edu:
                edu["typeEducation"] = edu.pop("degree")
            if "dateGraduation" not in edu and "year" in edu:
                edu["dateGraduation"] = edu.pop("year")
            if not edu.get("institution"):
                continue
            normalized_edu.append(edu)
        data["educations"] = normalized_edu
    else:
        data["educations"] = []

    # languages: accept list[str] or list[dict] with varying keys
    languages = data.get("languages") or []
    if isinstance(languages, list):
        proficiency_map = {
            "native": "NATIVE", "maternelle": "NATIVE", "natif": "NATIVE",
            "fluent": "C1", "courant": "C1", "bilingue": "C2",
            "advanced": "B2", "avance": "B2", "avancé": "B2",
            "intermediate": "B1", "intermediaire": "B1", "intermédiaire": "B1",
            "beginner": "A1", "debutant": "A1", "débutant": "A1", "basic": "A1",
        }
        valid_cefr = {"A1", "A2", "B1", "B2", "C1", "C2", "NATIVE"}
        normalized_langs: list[dict[str, Any]] = []
        for lang in languages:
            if isinstance(lang, str):
                m = re.match(r"^([^(\-–]+)[\s(\-–]+([^)]+)\)?$", lang.strip())
                if m:
                    name = m.group(1).strip()
                    prof_raw = m.group(2).strip().upper()
                    prof = prof_raw if prof_raw in valid_cefr else proficiency_map.get(m.group(2).strip().lower(), "B1")
                    normalized_langs.append({"language": name, "proficiency": prof})
                else:
                    normalized_langs.append({"language": lang.strip(), "proficiency": "B1"})
            elif isinstance(lang, dict):
                name = lang.get("language") or lang.get("name") or ""
                raw = str(lang.get("proficiency") or lang.get("level") or "B1").strip()
                prof = raw.upper() if raw.upper() in valid_cefr else proficiency_map.get(raw.lower(), "B1")
                if name:
                    normalized_langs.append({"language": str(name), "proficiency": prof})
        data["languages"] = normalized_langs
    else:
        data["languages"] = []

    # certifications: accept list[str] or list[dict]
    certs = data.get("certifications") or []
    if isinstance(certs, list):
        normalized_certs: list[dict[str, Any]] = []
        for c in certs:
            if isinstance(c, str) and c.strip():
                normalized_certs.append({"title": c.strip()})
            elif isinstance(c, dict):
                if "title" not in c:
                    c["title"] = c.get("name") or c.get("certification") or ""
                if c.get("title"):
                    normalized_certs.append(c)
        data["certifications"] = normalized_certs
    else:
        data["certifications"] = []

    # achievements: accept list[str] or list[dict]
    achievements = data.get("achievements") or []
    if isinstance(achievements, list):
        normalized_ach: list[dict[str, Any]] = []
        for item in achievements:
            if isinstance(item, str) and item.strip():
                normalized_ach.append({"title": item.strip()})
            elif isinstance(item, dict):
                title = item.get("title") or item.get("name") or item.get("project")
                if not title:
                    continue
                normalized_ach.append({
                    "title": str(title).strip(),
                    "description": str(item.get("description") or "").strip() or None,
                    "startDate": item.get("startDate") or item.get("start_date"),
                    "endDate": item.get("endDate") or item.get("end_date"),
                })
        data["achievements"] = normalized_ach
    else:
        data["achievements"] = []

    return data


class EntityExtractor:
    """Two-pass entity extraction: regex then LLM structured extraction."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def extract(self, *, cv_text: str, detected_language: str, extraction_notes: str) -> CandidateProfile:
        start = time.perf_counter()
        regex_email = _first_match(_EMAIL_RE, cv_text)
        regex_phone = _extract_phone(cv_text)
        pii = _extract_pii_entities(cv_text, detected_language)

        redacted_text = _redact_pii(
            _strip_header_zone(cv_text),
            pii.get("person_terms", []),
            pii.get("location_terms", []),
            pii.get("dob"),
        )

        data: dict[str, Any] = await self._llm.complete_json(
            prompt_key="cv_entity_extraction",
            variables={
                "detected_language": detected_language,
                "extraction_notes": extraction_notes,
                "cv_text": redacted_text[:30000],
            },
        )

        data = _normalize_llm_output(data)

        # Skills/establishments/languages are resolved against the catalog by
        # enrich_profile (the single resolution chokepoint), called by every
        # caller of extract() after this returns. Gemini returns canonical
        # *names* (codes never reach the LLM); enrich_profile converts names to
        # codes and drops anything off-catalog.

        # Build the employee block from local PII extraction (never from Gemini)
        name = pii.get("name") or "Unknown"
        firstname, lastname = _split_name(name)
        phone = _normalize_phone(regex_phone) if regex_phone else None

        employee = EmployeeInfo(
            firstname=firstname or None,
            lastname=lastname or None,
            email=regex_email,
            phone=phone,
            function=data.pop("function", None) or data.pop("current_title", None),
        )
        # Location from spaCy maps to region/workingSite
        location = pii.get("location")
        if location:
            employee.region = location

        data["employee"] = employee.model_dump(mode="json")

        # Remove old-schema PII fields that Gemini might have output
        for key in ("name", "email", "phone", "location", "current_title",
                     "linkedin_url", "github_url", "portfolio_url",
                     "total_experience_years"):
            data.pop(key, None)

        entity_extraction_duration_seconds.observe(time.perf_counter() - start)
        return CandidateProfile.model_validate(data, strict=False)
