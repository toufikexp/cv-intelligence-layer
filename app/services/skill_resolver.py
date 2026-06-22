from __future__ import annotations

from app.models.schemas import CandidateProfile
from app.services.catalog_store import CatalogStore


def enrich_profile(profile: CandidateProfile, store: CatalogStore) -> None:
    """Fill missing catalog codes, in place.

    Skills are already stored as ``{skill: <code>, score}`` (the extractor
    resolves Gemini's canonical names to codes; SkillConnect sync-in supplies
    codes directly), so nothing to enrich there. Languages: resolve
    ``language`` name → ``languageCode`` from the catalog. Unmatched → leave
    None (never fabricate).
    """
    for lg in profile.languages:
        if lg.language and not lg.languageCode:
            lg.languageCode = store.language_code(lg.language)
