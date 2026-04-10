from __future__ import annotations

from fastapi import APIRouter

from app.api.collections import router as collections_router
from app.api.cv import router as cv_router
from app.api.health import router as health_router
from app.api.ranking import router as ranking_router
from app.api.scoring import router as scoring_router
from app.api.webhooks import router as webhooks_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["Health"])
api_router.include_router(cv_router, prefix="/api/v1", tags=["Candidates"])
api_router.include_router(collections_router, prefix="/api/v1", tags=["Collections"])
api_router.include_router(ranking_router, prefix="/api/v1", tags=["Ranking"])
api_router.include_router(scoring_router, prefix="/api/v1", tags=["Answer Scoring"])
api_router.include_router(webhooks_router, tags=["Webhooks"])

