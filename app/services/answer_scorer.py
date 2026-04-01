from __future__ import annotations

import uuid
from typing import Any

from app.models.schemas import AnswerQuestion, AnswerScore, KeyConcepts
from app.services.llm_client import LLMClient
from app.services.search_client import SemanticSearchClient
from app.utils.language_detect import detect_language


class AnswerScorer:
    def __init__(self, *, search: SemanticSearchClient, llm: LLMClient) -> None:
        self._search = search
        self._llm = llm

    async def score_question(
        self,
        *,
        collection_id: uuid.UUID,
        q: AnswerQuestion,
        use_llm_grading: bool,
    ) -> AnswerScore:
        # Tier 1: embedding similarity via search
        search_resp = await self._search.search(
            collection_id=collection_id,
            query=q.candidate_answer,
            limit=1,
            offset=0,
            mode="hybrid",
            rerank=True,
        )
        hits = search_resp.get("results") or search_resp.get("hits") or []
        embedding_score = float((hits[0].get("score") if hits else 0.0) or 0.0)

        if embedding_score >= 0.7 or not use_llm_grading:
            points = round((embedding_score * q.max_points) * 2) / 2
            return AnswerScore(
                question_id=q.question_id,
                similarity_score=embedding_score,
                points_awarded=points,
                max_points=q.max_points,
                scoring_method="embedding",
                feedback=None,
            )

        if embedding_score < 0.3:
            points = 0.0
            return AnswerScore(
                question_id=q.question_id,
                similarity_score=embedding_score,
                points_awarded=points,
                max_points=q.max_points,
                scoring_method="embedding",
                feedback="Answer does not appear to address the question.",
            )

        # Tier 2: LLM grading
        answer_language = await detect_language(q.candidate_answer)
        llm_json: dict[str, Any] = await self._llm.complete_json(
            prompt_key="answer_scoring",
            variables={
                "question_text": q.question_text,
                "question_type": q.question_type,
                "max_points": q.max_points,
                "answer_language": answer_language,
                "reference_answer": q.reference_answer,
                "grading_rubric": q.grading_rubric or "",
                "candidate_answer": q.candidate_answer,
            },
        )
        return AnswerScore(
            question_id=q.question_id,
            similarity_score=float(llm_json.get("similarity_score", embedding_score)),
            points_awarded=float(llm_json.get("points_awarded", 0.0)),
            max_points=q.max_points,
            scoring_method="llm",
            accuracy_assessment=llm_json.get("accuracy_assessment"),
            completeness_assessment=llm_json.get("completeness_assessment"),
            feedback=llm_json.get("feedback"),
            key_concepts=KeyConcepts(
                covered=(llm_json.get("key_concepts") or {}).get("covered", []),
                missed=(llm_json.get("key_concepts") or {}).get("missed", []),
            ),
        )

