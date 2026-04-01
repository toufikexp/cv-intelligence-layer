from __future__ import annotations

from fastapi import APIRouter

from app.api.routes_collections import router as collections_router
from app.api.routes_cv import router as cv_router
from app.api.routes_health import router as health_router
from app.api.routes_ranking import router as ranking_router
from app.api.routes_scoring import router as scoring_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["Health"])
api_router.include_router(cv_router, prefix="/api/v1", tags=["CV Management"])
api_router.include_router(collections_router, prefix="/api/v1", tags=["Collections"])
api_router.include_router(ranking_router, prefix="/api/v1", tags=["Ranking"])
api_router.include_router(scoring_router, prefix="/api/v1", tags=["Answer Scoring"])

