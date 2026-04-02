from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_api_key
from app.models.database import get_db
from app.models.schemas import RankingRequest, RankingResponse
from app.services.llm_client import get_llm_client
from app.services.ranking_engine import RankingEngine
from app.services.search_client import get_search_client

router = APIRouter()


@router.post("/cv/rank", response_model=RankingResponse)
async def rank_candidates(
    req: RankingRequest,
    _: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
) -> RankingResponse:
    search = get_search_client()
    llm = get_llm_client()
    try:
        engine = RankingEngine(search=search, llm=llm)
        result = await engine.rank(db=db, req=req)
    finally:
        await search.aclose()
    return RankingResponse(results=result.results, job_id=result.job_id, took_ms=result.took_ms)

