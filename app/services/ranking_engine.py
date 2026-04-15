from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import CVProfile
from app.models.schemas import (
    CandidateProfile,
    RankedCandidate,
    RankingRequest,
    RecommendationEnum,
    SkillsAnalysis,
)
from app.services.llm_client import LLMClient
from app.services.search_client import SemanticSearchClient


@dataclass(frozen=True)
class RankingResult:
    job_id: uuid.UUID
    took_ms: int
    results: list[RankedCandidate]


DEFAULT_WEIGHTS = {"semantic": 0.30, "skills": 0.25, "experience": 0.25, "education": 0.10, "language": 0.10}


class RankingEngine:
    def __init__(self, *, search: SemanticSearchClient, llm: LLMClient) -> None:
        self._search = search
        self._llm = llm

    async def rank(self, *, db: AsyncSession, req: RankingRequest) -> RankingResult:
        start = time.perf_counter()
        settings = get_settings()
        recall_size = req.recall_size or settings.ranking_default_recall_size

        search_resp = await self._search.search(
            collection_id=req.collection_id,
            query=req.job_description,
            limit=recall_size,
            offset=0,
            mode="hybrid",
            rerank=True,
        )

        hits = search_resp.get("results") or search_resp.get("hits") or []
        # expected hit shape: {external_id, score, metadata, ...}
        external_ids = [h.get("external_id") for h in hits if h.get("external_id")]

        # Index CVs by every possible correlation key so `cvs.get(ext_id)`
        # resolves regardless of whether the document was indexed under the
        # caller-supplied external_id (new contract), the legacy
        # search_doc_external_id, or the file_hash fallback (pre-0003 rows).
        cvs: dict[str, CVProfile] = {}
        if external_ids:
            res = await db.execute(select(CVProfile).where(CVProfile.collection_id == req.collection_id))
            for cv in res.scalars().all():
                if cv.external_id and cv.external_id in external_ids:
                    cvs[cv.external_id] = cv
                if cv.search_doc_external_id and cv.search_doc_external_id in external_ids:
                    cvs[cv.search_doc_external_id] = cv
                if cv.file_hash in external_ids:
                    cvs[cv.file_hash] = cv

        weights = DEFAULT_WEIGHTS.copy()
        if req.weights:
            weights.update({k: v for k, v in req.weights.model_dump().items() if v is not None})

        sem = asyncio.Semaphore(settings.ranking_llm_concurrency)

        async def eval_one(hit: dict[str, Any]) -> RankedCandidate | None:
            ext_id = hit.get("external_id")
            if not ext_id:
                return None
            cv = cvs.get(ext_id)
            if not cv or not cv.profile_data:
                return None
            profile = CandidateProfile.model_validate(cv.profile_data, strict=False)

            async with sem:
                llm_json = await self._llm.complete_json(
                    prompt_key="cv_ranking",
                    variables={
                        "job_description": req.job_description,
                        "required_skills": req.required_skills or [],
                        "preferred_skills": req.preferred_skills or [],
                        "min_experience_years": req.min_experience_years,
                        "required_languages": req.required_languages or [],
                        "education_requirements": req.education_requirements or "",
                        "candidate_name": profile.name,
                        "current_title": profile.current_title or "",
                        "location": profile.location or "",
                        "total_experience_years": profile.total_experience_years or 0,
                        "skills": profile.skills,
                        "languages": [f"{le.language} ({le.level})" for le in profile.languages],
                        "experience_details": "\n".join(
                            f"- {e.role} @ {e.company} ({e.start_date or ''} - {e.end_date or ''}): {e.description or ''}"
                            for e in profile.experience
                        ),
                        "education_details": "\n".join(
                            f"- {e.degree or ''} {e.field or ''} — {e.institution} ({e.year or ''})"
                            for e in profile.education
                        ),
                        "achievements_details": "\n".join(
                            f"- {a.title}"
                            + (f" ({a.year})" if a.year else "")
                            + (f": {a.description}" if a.description else "")
                            for a in profile.achievements
                        ) or "(none)",
                        "summary": profile.summary or "",
                    },
                )

            semantic_score = float(hit.get("score") or hit.get("semantic_score") or 0.0)
            skills_score = float(llm_json.get("skills_score", 0.0))
            experience_score = float(llm_json.get("experience_score", 0.0))
            education_score = float(llm_json.get("education_score", 0.0))
            language_score = float(llm_json.get("language_score", 0.0))
            composite = (
                weights["semantic"] * semantic_score
                + weights["skills"] * skills_score
                + weights["experience"] * experience_score
                + weights["education"] * education_score
                + weights["language"] * language_score
            )

            rec_raw = llm_json.get("recommendation", "partial_match")
            allowed: set[str] = {"strong_match", "good_match", "partial_match", "weak_match"}
            rec: RecommendationEnum = rec_raw if rec_raw in allowed else "partial_match"  # type: ignore[assignment]

            return RankedCandidate(
                cv_id=cv.cv_id,
                external_id=cv.external_id,
                score=composite,
                recommendation=rec,
                reasoning=llm_json.get("reasoning", ""),
                skills_analysis=SkillsAnalysis(
                    matched_required=(llm_json.get("skills_analysis", {}) or {}).get("matched_required", []),
                    missing_required=(llm_json.get("skills_analysis", {}) or {}).get("missing_required", []),
                ),
            )

        ranked = [r for r in await asyncio.gather(*(eval_one(h) for h in hits)) if r is not None]
        ranked.sort(key=lambda r: r.score, reverse=True)

        took_ms = int((time.perf_counter() - start) * 1000)
        return RankingResult(job_id=uuid.uuid4(), took_ms=took_ms, results=ranked)

