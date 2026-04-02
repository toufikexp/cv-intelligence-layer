"""Tests for the answer scorer hybrid strategy."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.models.schemas import AnswerQuestion
from app.services.answer_scorer import AnswerScorer


def _make_question(**overrides: object) -> AnswerQuestion:
    defaults = {
        "question_id": "q1",
        "question_text": "What is OOP?",
        "question_type": "conceptual",
        "reference_answer": "Object-oriented programming is a paradigm...",
        "candidate_answer": "OOP is about classes and objects.",
        "max_points": 10,
    }
    defaults.update(overrides)
    return AnswerQuestion(**defaults)


@pytest.mark.asyncio
async def test_high_embedding_score_fast_path(mock_llm_client: AsyncMock) -> None:
    """Embedding score >= 0.7 should skip LLM and use embedding method."""
    search = AsyncMock()
    search.search.return_value = {"results": [{"score": 0.85}]}
    search.aclose.return_value = None

    scorer = AnswerScorer(search=search, llm=mock_llm_client)
    result = await scorer.score_question(
        collection_id=uuid.uuid4(),
        q=_make_question(),
        use_llm_grading=True,
    )

    assert result.scoring_method == "embedding"
    assert result.similarity_score == pytest.approx(0.85)
    assert result.points_awarded > 0


@pytest.mark.asyncio
async def test_low_embedding_score_flagged(mock_llm_client: AsyncMock) -> None:
    """Embedding score < 0.3 should flag as insufficient without LLM."""
    search = AsyncMock()
    search.search.return_value = {"results": [{"score": 0.15}]}
    search.aclose.return_value = None

    scorer = AnswerScorer(search=search, llm=mock_llm_client)
    result = await scorer.score_question(
        collection_id=uuid.uuid4(),
        q=_make_question(),
        use_llm_grading=True,
    )

    assert result.scoring_method == "embedding"
    assert result.points_awarded == 0.0
    assert result.feedback is not None
    assert "insufficient" in result.feedback.lower() or "does not" in result.feedback.lower()


@pytest.mark.asyncio
async def test_mid_embedding_score_escalates_to_llm(mock_llm_client: AsyncMock) -> None:
    """Embedding score between 0.3 and 0.7 should escalate to LLM grading."""
    search = AsyncMock()
    search.search.return_value = {"results": [{"score": 0.5}]}
    search.aclose.return_value = None

    scorer = AnswerScorer(search=search, llm=mock_llm_client)
    result = await scorer.score_question(
        collection_id=uuid.uuid4(),
        q=_make_question(),
        use_llm_grading=True,
    )

    assert result.scoring_method == "llm"
    assert result.points_awarded == pytest.approx(7.5)
    assert result.feedback is not None


@pytest.mark.asyncio
async def test_llm_grading_disabled(mock_llm_client: AsyncMock) -> None:
    """When use_llm_grading=False, always use embedding regardless of score."""
    search = AsyncMock()
    search.search.return_value = {"results": [{"score": 0.5}]}
    search.aclose.return_value = None

    scorer = AnswerScorer(search=search, llm=mock_llm_client)
    result = await scorer.score_question(
        collection_id=uuid.uuid4(),
        q=_make_question(),
        use_llm_grading=False,
    )

    assert result.scoring_method == "embedding"
