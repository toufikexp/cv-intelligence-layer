# CV Ranking & Scoring Skill

This skill covers the Ranking Engine + Answer Scorer components.

## Ranking Engine

Two-phase ranking:

### Phase 1: Semantic Recall
- Use `search_client.search(collection_id, query=job_description, mode="hybrid", rerank=True, limit=recall_size)`
- Default recall_size: 30
- This is FAST (< 500ms) — always do this first

### Phase 2: LLM Evaluation
- For each candidate from Phase 1, call Claude Sonnet with `prompts/cv_ranking.md` template
- Parallelize with `asyncio.Semaphore(RANKING_LLM_CONCURRENCY)` — default 5
- Each LLM call returns: skills_score, experience_score, education_score, language_score, reasoning

### Composite Score
```python
composite = (
    weights.semantic * search_score +
    weights.skills * llm_result.skills_score +
    weights.experience * llm_result.experience_score +
    weights.education * llm_result.education_score +
    weights.language * llm_result.language_score
)
# Defaults: 0.30, 0.25, 0.25, 0.10, 0.10
```

- Cache results in `cv_ranking_results` table to avoid recomputation
- For > 30 candidates: make it async (return job_id)

## Answer Scorer

### Hybrid strategy
```python
if embedding_score >= 0.7:
    return score, method="embedding"     # fast, no LLM cost
elif embedding_score >= 0.3:
    return llm_score, method="llm"       # detailed feedback
else:
    return score, method="embedding"     # flag as insufficient
```

- Reference answers go into a dedicated Search collection per test
- Candidate answer is the search query → score is the similarity
- LLM grading uses `prompts/answer_scoring.md` template
- Aggregate: `total_score = sum(points_awarded) / sum(max_points) * 100`
