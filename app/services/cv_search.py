from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import CVProfile
from app.models.schemas import CVSearchRequest, CVSearchResponse, CVSearchResult
from app.services.search_client import SemanticSearchClient


class CVSearchService:
    """Search indexed CVs via Semantic Search and map ``external_id`` → ``cv_id``."""

    async def search(
        self,
        *,
        db: AsyncSession,
        client: SemanticSearchClient,
        req: CVSearchRequest,
    ) -> CVSearchResponse:
        t0 = time.perf_counter()
        query_id = uuid.uuid4()
        raw = await client.search(
            collection_id=req.collection_id,
            query=req.query,
            filters=req.filters,
            limit=req.limit,
            offset=req.offset,
            facets=req.facets,
            mode="hybrid",
            rerank=True,
        )
        took_ms = int((time.perf_counter() - t0) * 1000)
        hits: list[dict[str, Any]] = list(raw.get("results") or raw.get("hits") or [])
        total = int(raw.get("total") if raw.get("total") is not None else len(hits))
        facets = raw.get("facets")

        ext_ids = [str(h.get("external_id")) for h in hits if h.get("external_id")]
        by_hash: dict[str, CVProfile] = {}
        if ext_ids:
            res = await db.execute(
                select(CVProfile).where(
                    CVProfile.collection_id == req.collection_id,
                    CVProfile.file_hash.in_(ext_ids),
                )
            )
            for row in res.scalars().all():
                by_hash[row.file_hash] = row

        results: list[CVSearchResult] = []
        for h in hits:
            ext = h.get("external_id")
            ext_s = str(ext) if ext is not None else None
            cv = by_hash.get(ext_s) if ext_s else None
            score = h.get("score")
            if score is None:
                score = h.get("semantic_score")
            meta = h.get("metadata") or {}
            cand_name = cv.candidate_name if cv else meta.get("candidate_name")
            profile_data = cv.profile_data if cv else None
            current_title = None
            location = None
            skills = None
            exp_years = None
            if isinstance(profile_data, dict):
                current_title = profile_data.get("current_title")
                location = profile_data.get("location")
                skills = profile_data.get("skills")
                exp_years = profile_data.get("total_experience_years")
            if meta.get("skills") is not None:
                skills = meta.get("skills")
            if meta.get("experience_years") is not None:
                exp_years = meta.get("experience_years")
            if meta.get("location") is not None:
                location = meta.get("location")

            results.append(
                CVSearchResult(
                    cv_id=cv.cv_id if cv else None,
                    score=float(score) if score is not None else None,
                    candidate_name=cand_name,
                    current_title=current_title,
                    location=location,
                    skills=skills if isinstance(skills, list) else None,
                    experience_years=float(exp_years) if exp_years is not None else None,
                    highlights=None,
                )
            )

        return CVSearchResponse(
            results=results,
            facets=facets if isinstance(facets, dict) else None,
            total=total,
            query_id=query_id,
            took_ms=took_ms,
        )


def get_cv_search_service() -> CVSearchService:
    return CVSearchService()
