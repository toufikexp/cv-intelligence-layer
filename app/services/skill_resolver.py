from __future__ import annotations

from app.models.schemas import CandidateProfile
from app.services.catalog_store import CatalogStore


class EstablishmentValidationError(ValueError):
    """Raised when an education entry has an unresolvable establishment."""

    def __init__(self, unmatched: list[str]) -> None:
        self.unmatched = unmatched
        names = ", ".join(unmatched)
        super().__init__(
            f"Establishment(s) not found in catalog: {names}. "
            "Use a catalog code or a name that matches the catalog."
        )


def enrich_profile(
    profile: CandidateProfile,
    store: CatalogStore,
    *,
    strict_establishments: bool = True,
) -> None:
    """Resolve/validate catalog references against the catalog, in place.

    This is the single resolution chokepoint for every path that produces a
    profile (file extraction, the JSON sync-in on ``POST /candidates``, and
    ``PATCH``).

    - **Skills**: each ``skill`` must end up as a catalog CODE. A value that is
      already a valid code is kept; a value matching a catalog *name* is
      converted to its code; anything off-catalog is dropped.
    - **Educations**: ``establishment`` arrives as a school/university name
      (from Gemini similarity matching) or a catalog code. It is resolved to a
      catalog code when possible. ``institution`` is the type of institution
      (école, université, centre, etc.) and is left as-is.
      - ``strict_establishments=True`` (create/patch): raises
        ``EstablishmentValidationError`` if any establishment cannot be resolved
        to a catalog code.
      - ``strict_establishments=False`` (extract/upload): keeps the raw name
        when no catalog match is found.
    - **Languages**: ``languageCode`` resolved from the language name.
    """
    # --- skills: every stored skill must be a catalog code -------------------
    resolved_skills = []
    for sk in profile.skills:
        val = (sk.skill or "").strip()
        if not val:
            continue
        if store.skill_name(val) is not None:
            resolved_skills.append(sk)
            continue
        code = store.skill_code(val)
        if code is not None:
            sk.skill = code
            resolved_skills.append(sk)
    profile.skills = resolved_skills

    # --- educations: resolve establishment name → code ----------------------
    unmatched_establishments: list[str] = []
    for edu in profile.educations:
        raw = (edu.establishment or "").strip()
        if not raw:
            continue
        # Already a valid catalog code?
        if store.establishment_name(raw) is not None:
            continue
        # Try to resolve name → code
        code = store.establishment_code(raw)
        if code is not None:
            edu.establishment = code
        elif strict_establishments:
            unmatched_establishments.append(raw)
        # else: keep raw name (extract/upload tolerance)

    if unmatched_establishments:
        raise EstablishmentValidationError(unmatched_establishments)

    # --- languages: resolve languageCode from the language name --------------
    for lg in profile.languages:
        if lg.language and not lg.languageCode:
            lg.languageCode = store.language_code(lg.language)
