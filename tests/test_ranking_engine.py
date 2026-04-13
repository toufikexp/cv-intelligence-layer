"""Tests for the two-phase ranking engine."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.database import CVProfile
from app.models.schemas import CandidateProfile, RankingRequest
from app.services.ranking_engine import DEFAULT_WEIGHTS, RankingEngine


def _make_cv(file_hash: str, profile: CandidateProfile) -> CVProfile:
    now = datetime.now(timezone.utc)
    return CVProfile(
        cv_id=uuid.uuid4(),
        external_id=file_hash,
        collection_id=uuid.uuid4(),
        file_hash=file_hash,
        search_doc_external_id=file_hash,
        profile_data=profile.model_dump(mode="json"),
        candidate_name=profile.name,
        status="ready",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_rank_composite_score(
    fake_candidate_profile: CandidateProfile,
    mock_search_client: AsyncMock,
    mock_llm_client: AsyncMock,
) -> None:
    cv = _make_cv("abc123deadbeef", fake_candidate_profile)

    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [cv]
    mock_db.execute = AsyncMock(return_value=exec_result)

    engine = RankingEngine(search=mock_search_client, llm=mock_llm_client)
    req = RankingRequest(
        collection_id=cv.collection_id,
        job_description="Python developer with FastAPI experience",
        required_skills=["Python", "FastAPI"],
    )
    result = await engine.rank(db=mock_db, req=req)

    assert len(result.results) == 1
    candidate = result.results[0]
    assert candidate.cv_id == cv.cv_id
    assert candidate.external_id == "abc123deadbeef"

    # Verify composite score: semantic=0.85, skills=0.8, exp=0.7, edu=0.6, lang=0.9
    w = DEFAULT_WEIGHTS
    expected = w["semantic"] * 0.85 + w["skills"] * 0.8 + w["experience"] * 0.7 + w["education"] * 0.6 + w["language"] * 0.9
    assert candidate.score == pytest.approx(expected, abs=0.01)
    assert candidate.recommendation == "good_match"


@pytest.mark.asyncio
async def test_rank_empty_search_results(
    mock_llm_client: AsyncMock,
) -> None:
    empty_search = AsyncMock()
    empty_search.search.return_value = {"results": [], "total": 0}
    empty_search.aclose.return_value = None

    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=exec_result)

    engine = RankingEngine(search=empty_search, llm=mock_llm_client)
    req = RankingRequest(
        collection_id=uuid.uuid4(),
        job_description="Any job",
    )
    result = await engine.rank(db=mock_db, req=req)
    assert result.results == []


@pytest.mark.asyncio
async def test_rank_multiple_sorted(
    mock_llm_client: AsyncMock,
) -> None:
    """Two candidates should be sorted by composite score descending."""

    profile_a = CandidateProfile(name="Alice", skills=["Python"])
    profile_b = CandidateProfile(name="Bob", skills=["Java"])
    cv_a = _make_cv("hash_a", profile_a)
    cv_b = _make_cv("hash_b", profile_b)
    cv_b.collection_id = cv_a.collection_id

    search_client = AsyncMock()
    search_client.search.return_value = {
        "results": [
            {"external_id": "hash_a", "score": 0.9},
            {"external_id": "hash_b", "score": 0.5},
        ],
        "total": 2,
    }
    search_client.aclose.return_value = None

    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [cv_a, cv_b]
    mock_db.execute = AsyncMock(return_value=exec_result)

    engine = RankingEngine(search=search_client, llm=mock_llm_client)
    req = RankingRequest(
        collection_id=cv_a.collection_id,
        job_description="Developer",
    )
    result = await engine.rank(db=mock_db, req=req)

    assert len(result.results) == 2
    assert result.results[0].score >= result.results[1].score
