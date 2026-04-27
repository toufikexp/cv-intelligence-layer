# CV Ranking & Scoring Skill

Covers the Ranking Engine (`app/services/ranking_engine.py`) and the Answer
Scorer (`app/services/answer_scorer.py`).

## Ranking Engine

Two-phase ranking, fully synchronous. The pipeline is the same regardless of
candidate-set size.

### Phase 1 — Semantic Recall

```python
search_resp = await search_client.search(
    collection_id=req.collection_id,
    query=req.job_description,
    mode="hybrid",
    rerank=True,
    limit=recall_size,   # default 30 via RANKING_DEFAULT_RECALL_SIZE
)
```

- Always `mode="hybrid"`, always `rerank=True`
- Hits are joined back to local `CVProfile` rows by every possible key
  (`external_id`, legacy `search_doc_external_id`, legacy `file_hash`) so
  pre-migration rows still resolve. New rows always match on `external_id`.
- Hits whose CV has `profile_data is None` are dropped silently — there's
  nothing to score against.

### Phase 2 — LLM Evaluation

For each surviving hit, call `LLMClient.complete_json(prompt_key="cv_ranking")`
with these variables (see `prompts/cv_ranking.md`):

```
job_description, required_skills, preferred_skills,
min_experience_years, required_languages, education_requirements,
candidate_name, current_title, location, total_experience_years,
skills, languages, experience_details, education_details,
achievements_details, summary
```

Parallelism: `asyncio.Semaphore(RANKING_LLM_CONCURRENCY)` — default 5.

LLM returns: `skills_score`, `experience_score`, `education_score`,
`language_score`, `recommendation`, `reasoning`, and the structured
`skills_analysis: {matched_required, missing_required, ...}`.

### Composite Score

```python
composite = (
    weights.semantic   * semantic_score
  + weights.skills     * llm.skills_score
  + weights.experience * llm.experience_score
  + weights.education  * llm.education_score
  + weights.language   * llm.language_score
)
# Defaults: semantic=0.30, skills=0.25, experience=0.25, education=0.10, language=0.10
```

- The semantic score serves dual purpose: shortlisting (recall) AND scoring (30% weight).
- Weights are overridable per request via `RankingRequest.weights` —
  null fields fall back to defaults; non-null fields replace them.
- Hits are sorted by `composite` descending before return.

### Response shape

```python
RankingResponse(
    results=[RankedCandidate(
        cv_id, external_id, score, recommendation, reasoning, skills_analysis,
    )],
    job_id=uuid4(),  # ephemeral, not persisted today
    took_ms,
)
```

`recommendation ∈ {strong_match, good_match, partial_match, weak_match}`. If
the LLM returns an unrecognized value, the engine falls back to
`partial_match`.

### Caching

The `cv_ranking_results` table exists to cache `(job_id, cv_id) → composite_score`.
Today the engine generates an ephemeral `job_id` per request and does NOT
persist results — caching is reserved for a future optimization. Don't write
code that assumes results are stored.

### API Endpoint

`POST /api/v1/candidates/rank`

## Answer Scorer

### Hybrid strategy

```python
embedding_score = float(top_hit.score)  # from Semantic Search

if embedding_score >= 0.7 or not use_llm_grading:
    method = "embedding"
    points = round(embedding_score * max_points * 2) / 2  # nearest 0.5
elif embedding_score < 0.3:
    method = "embedding"
    points = 0.0   # flagged as insufficient
else:
    method = "llm"
    # detect language of the candidate answer (independent of CV language)
    # then call prompts/answer_scoring.md
```

- Reference answers go into a dedicated Search collection per test
- The candidate's answer is the search query — the top hit's score is the
  similarity
- `ScoringMethod` literal includes `hybrid` for forward-compat, but only
  `embedding` and `llm` are emitted today
- LLM grading uses `prompts/answer_scoring.md` and the candidate-answer's
  detected language (so an English answer to a French question still grades
  with English context)
- Aggregation in the route handler:
  `total = sum(points_awarded)`,
  `score_percentage = total / sum(max_points) * 100`

### API Endpoint

`POST /api/v1/candidates/score-answers`
