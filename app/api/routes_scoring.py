from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth import get_api_key
from app.models.schemas import AnswerScoringRequest, AnswerScoringResponse
from app.services.answer_scorer import AnswerScorer
from app.services.llm_client import get_llm_client
from app.services.search_client import get_search_client

router = APIRouter()


@router.post("/cv/score-answers", response_model=AnswerScoringResponse)
async def score_answers(
    req: AnswerScoringRequest,
    _: str = Depends(get_api_key),
) -> AnswerScoringResponse:
    search = get_search_client()
    llm = get_llm_client()
    scorer = AnswerScorer(search=search, llm=llm)
    try:
        results = []
        total = 0.0
        max_total = 0.0
        for q in req.questions:
            s = await scorer.score_question(collection_id=req.collection_id, q=q, use_llm_grading=req.use_llm_grading)
            results.append(s)
            total += s.points_awarded
            max_total += s.max_points
        pct = (total / max_total * 100.0) if max_total > 0 else 0.0
        return AnswerScoringResponse(
            results=results,
            total_score=total,
            max_score=max_total,
            score_percentage=pct,
            cv_id=req.cv_id,
        )
    finally:
        await search.aclose()

