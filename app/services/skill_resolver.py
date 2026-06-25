from __future__ import annotations

from app.models.schemas import CandidateProfile
from app.services.catalog_store import CatalogStore


class CatalogValidationError(ValueError):
    """Raised when a profile references skills/establishments not in the catalog.

    Only raised in strict mode (create/patch). The extract/upload paths are
    tolerant: off-catalog skills are dropped and unmatched establishments keep
    their raw name.
    """

    def __init__(
        self,
        *,
        skills: list[str] | None = None,
        establishments: list[str] | None = None,
    ) -> None:
        self.unmatched_skills = skills or []
        self.unmatched_establishments = establishments or []
        parts: list[str] = []
        if self.unmatched_skills:
            parts.append(f"skill(s): {', '.join(self.unmatched_skills)}")
        if self.unmatched_establishments:
            parts.append(f"establishment(s): {', '.join(self.unmatched_establishments)}")
        super().__init__(
            "Not found in catalog — " + "; ".join(parts) + ". "
            "Use a catalog code, or a name/value that matches the catalog."
        )


# Backwards-compatible alias (older imports).
EstablishmentValidationError = CatalogValidationError


def enrich_profile(
    profile: CandidateProfile,
    store: CatalogStore,
    *,
    strict: bool = True,
) -> None:
    """Resolve/validate catalog references against the catalog, in place.

    This is the single resolution chokepoint for every path that produces a
    profile (file extraction, the JSON sync-in on ``POST /candidates``, and
    ``PATCH``).

    - **Skills**: each ``skill`` must end up as a catalog CODE. A value that is
      already a valid code is kept; a value matching a catalog *name* is
      converted to its code.
      - ``strict=True`` (create/patch): an off-catalog skill raises
        ``CatalogValidationError`` (never silently dropped — that would wipe a
        caller's data without warning).
      - ``strict=False`` (extract/upload): off-catalog skills are dropped, since
        Gemini may surface near-matches that should not fail the whole pipeline.
    - **Educations**: ``establishment`` arrives as a school/university name
      (Gemini similarity match) or a catalog code, and is resolved to a code.
      ``institution`` is the *type* of institution and is left untouched.
      - ``strict=True``: unresolved establishment raises ``CatalogValidationError``.
      - ``strict=False``: unresolved establishment keeps its raw name.
    - **Languages**: ``languageCode`` resolved from the language name (always
      best-effort; unmatched → ``None``).
    """
    unmatched_skills: list[str] = []
    unmatched_establishments: list[str] = []

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
        elif strict:
            unmatched_skills.append(val)
        # else: off-catalog → drop (tolerant mode)
    profile.skills = resolved_skills

    # --- educations: resolve establishment name → code ----------------------
    for edu in profile.educations:
        raw = (edu.establishment or "").strip()
        if not raw:
            continue
        if store.establishment_name(raw) is not None:
            continue  # already a valid catalog code
        code = store.establishment_code(raw)
        if code is not None:
            edu.establishment = code
        elif strict:
            unmatched_establishments.append(raw)
        # else: keep raw name (tolerant mode)

    if unmatched_skills or unmatched_establishments:
        raise CatalogValidationError(
            skills=unmatched_skills,
            establishments=unmatched_establishments,
        )

    # --- languages: resolve languageCode from the language name --------------
    for lg in profile.languages:
        if lg.language and not lg.languageCode:
            lg.languageCode = store.language_code(lg.language)
