from __future__ import annotations

import logging
import re
import time
from typing import Any

import spacy

from app.models.schemas import CandidateProfile
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
# When the contact block yields no name (e.g. OCR merged the header into one
# long line, emptying the block), widen the name search to this many leading
# non-empty lines of the full text — still using the strict _looks_like_name.
_HEADER_NAME_SCAN_LINES = 12

# Section headings mark the end of the contact block. The candidate's
# name/location/DOB always appear before the first of these.
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

# Label words spaCy frequently mis-tags as LOC/GPE/PER in contact blocks.
# They get redacted harmlessly but must never be used as the stored value.
_PII_LABEL_WORDS = {
    "adresse", "address", "email", "e-mail", "mail", "courriel", "tel",
    "tél", "téléphone", "telephone", "phone", "mobile", "gsm", "fax",
    "contact", "nationalité", "nationality", "linkedin", "github",
}

_NAME_LINE_RE = re.compile(r"^[A-Za-zÀ-ÿ' .\-]{2,40}$")

_spacy_models: dict[str, spacy.Language] = {}


def load_spacy_models() -> None:
    """Load both spaCy NER models into module-level cache. Call once at startup."""
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
    """Return the CV's contact block: the non-empty lines before the first
    section heading or long prose line (the summary), capped for safety.

    Scoping NER to this block keeps summary/experience prose out of the
    entity scan, which otherwise produces false-positive PER/LOC entities.
    """
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
    """Use spaCy NER on the contact block to find name, location, and DOB.

    Returns the best single value for each field plus the full set of terms
    to scrub from the text (so e.g. both city and country are redacted, not
    just whichever entity spaCy happened to list first).
    """
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
    if not name:  # NER misses all-caps / mis-tagged names; fall back to a name-like line
        name = next(
            (line.strip() for line in block.split("\n") if _looks_like_name(line)),
            None,
        )
    if not name:
        # Safety net for OCR: a merged/garbled contact line can empty the
        # contact block (which cuts at the first line > _PROSE_LINE_LEN) while
        # the real name sits on a later header line. Re-scan the header zone —
        # non-empty lines BEFORE the first section heading, without the length
        # cutoff — and take the first that strictly looks like a name. This
        # never reads past a section heading, so experience/skill/title lines
        # stay out of scope; `_looks_like_name` rejects digits/@/labels and
        # caps at 4 tokens. Purely local — no LLM.
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
    """Replace all PII tokens with placeholders before sending to LLM."""
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


def _extract_phone(text: str) -> str | None:
    """Return the first phone-like match that is a real phone (9-15 digits, not a year range)."""
    for m in _PHONE_RE.finditer(text):
        cand = m.group(0).strip()
        digits = re.sub(r"\D", "", cand)
        if 9 <= len(digits) <= 15 and not _YEAR_RANGE_RE.match(cand):
            return cand
    return None


def _redact_phones(text: str) -> str:
    """Replace real phone numbers while leaving year ranges untouched."""
    def _repl(m: re.Match[str]) -> str:
        cand = m.group(0).strip()
        digits = re.sub(r"\D", "", cand)
        if 9 <= len(digits) <= 15 and not _YEAR_RANGE_RE.match(cand):
            return "[REDACTED_PHONE]"
        return m.group(0)
    return _PHONE_RE.sub(_repl, text)


def _strip_header_zone(text: str) -> str:
    """Replace everything before the first section heading (cap 8 lines)
    with a placeholder, so no header PII reaches the LLM."""
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
    """Count alphanumeric characters (including accented) for readability gating."""
    return len(re.findall(r"[A-Za-zÀ-ÿ0-9]", text))


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
        normalized_exp: list[dict[str, Any]] = []
        for exp in experience:
            if not isinstance(exp, dict):
                continue
            if "role" not in exp and "title" in exp:
                exp["role"] = exp.pop("title")
            if "role" not in exp and "position" in exp:
                exp["role"] = exp.pop("position")
            if "company" not in exp and "employer" in exp:
                exp["company"] = exp.pop("employer")
            if not exp.get("company"):
                exp["company"] = exp.get("role") or ""
            if not exp.get("role"):
                exp["role"] = exp.get("company") or ""
            if not exp["company"] and not exp["role"]:
                continue
            desc = exp.get("description")
            if isinstance(desc, list):
                exp["description"] = "\n".join(str(d).strip() for d in desc if d)
            elif isinstance(desc, dict):
                exp["description"] = "\n".join(f"{k}: {v}" for k, v in desc.items() if v)
            normalized_exp.append(exp)
        data["experience"] = normalized_exp

    # 4. Normalize education entries
    education = data.get("education") or []
    if isinstance(education, list):
        normalized_edu: list[dict[str, Any]] = []
        for edu in education:
            if not isinstance(edu, dict):
                continue
            if "field" not in edu and "field_of_study" in edu:
                edu["field"] = edu.pop("field_of_study")
            if "institution" not in edu and "school" in edu:
                edu["institution"] = edu.pop("school")
            if "institution" not in edu and "university" in edu:
                edu["institution"] = edu.pop("university")
            if not edu.get("institution"):
                edu["institution"] = edu.get("degree") or edu.get("field") or ""
            if not edu["institution"]:
                continue
            normalized_edu.append(edu)
        data["education"] = normalized_edu

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
        start = time.perf_counter()
        # Extract PII locally from the ORIGINAL text (before any stripping)
        regex_email = _first_match(_EMAIL_RE, cv_text)
        regex_phone = _extract_phone(cv_text)
        urls = _extract_urls(cv_text)
        pii = _extract_pii_entities(cv_text, detected_language)

        # Hard PII guarantee: strip header zone + defense-in-depth body redaction
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

        # Defensive normalization of Gemini output variations
        data = _normalize_llm_output(data)

        # Personal fields: spaCy/regex only — never use Gemini's guesses
        data["name"] = pii.get("name") or "Unknown"
        data["location"] = pii.get("location")
        if regex_email:
            data["email"] = regex_email
        if regex_phone:
            data["phone"] = _normalize_phone(regex_phone)
        elif not data.get("phone"):
            data["phone"] = None
        else:
            data["phone"] = None
        for k, v in urls.items():
            if v:
                data[k] = v

        entity_extraction_duration_seconds.observe(time.perf_counter() - start)
        return CandidateProfile.model_validate(data, strict=False)

