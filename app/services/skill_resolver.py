from __future__ import annotations

from app.models.schemas import CandidateProfile
from app.services.catalog_store import CatalogStore


def enrich_profile(profile: CandidateProfile, store: CatalogStore) -> None:
    """Fill missing codes from names and names from codes, in place.

    - Skills: code → name (from catalog); name → code (from catalog).
    - Languages: language name → languageCode (from catalog).
    - Unmatched → leave None (never fabricate).
    """
    for s in profile.skills:
        if s.skill and not s.name:
            s.name = store.skill_name(s.skill)
        if s.name and not s.skill:
            s.skill = store.skill_code(s.name)

    for lg in profile.languages:
        if lg.language and not lg.languageCode:
            lg.languageCode = store.language_code(lg.language)
