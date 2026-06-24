from __future__ import annotations

from app.models.schemas import CandidateProfile
from app.services.catalog_store import CatalogStore


def enrich_profile(profile: CandidateProfile, store: CatalogStore) -> None:
    """Resolve/validate catalog references against the catalog, in place.

    This is the single resolution chokepoint for every path that produces a
    profile (file extraction, the JSON sync-in on ``POST /candidates``, and
    ``PATCH``). It does NOT fabricate anything — values that do not match the
    catalog are dropped (skills) or left ``None`` (establishment/languageCode).

    - **Skills**: each ``skill`` must end up as a catalog CODE. A value that is
      already a valid code is kept; a value matching a catalog *name* is
      converted to its code; anything off-catalog is dropped. (Mirrors the
      file-extraction contract — Semantic Search and storage only ever hold
      catalog skills.)
    - **Educations**: ``institution`` is the free-text school name (kept as-is);
      ``establishment`` must end up as a catalog establishment CODE. If it is not
      already a valid code, it is resolved from ``institution`` (or from a name
      mistakenly placed in ``establishment``); unmatched → ``None``.
    - **Languages**: ``languageCode`` resolved from the language name.

    Note: ``company`` stays free-text — the SkillConnect doc defines no company
    catalog, so there is no ``companyId`` to resolve.
    """
    # --- skills: every stored skill must be a catalog code -------------------
    resolved_skills = []
    for sk in profile.skills:
        val = (sk.skill or "").strip()
        if not val:
            continue
        if store.skill_name(val) is not None:
            # already a valid catalog code
            resolved_skills.append(sk)
            continue
        code = store.skill_code(val)
        if code is not None:
            # value was a catalog name → store its code
            sk.skill = code
            resolved_skills.append(sk)
        # else: off-catalog → drop (never fabricate)
    profile.skills = resolved_skills

    # --- educations: institution (free text) + establishment (code) ----------
    for edu in profile.educations:
        if edu.establishment and store.establishment_name(edu.establishment) is not None:
            # already a valid establishment code
            continue
        name = edu.institution or edu.establishment
        edu.establishment = store.establishment_code(name) if name else None

    # --- languages: resolve languageCode from the language name --------------
    for lg in profile.languages:
        if lg.language and not lg.languageCode:
            lg.languageCode = store.language_code(lg.language)
