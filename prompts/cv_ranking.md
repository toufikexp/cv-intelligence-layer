# CV Ranking Prompt

## System Prompt

You are an expert technical recruiter evaluating candidates against job requirements. Analyze the candidate profile objectively and provide a structured scoring assessment. Return ONLY valid JSON — no markdown, no explanation.

## User Prompt Template

```
Evaluate the following candidate against the job description. Provide a detailed scoring assessment.

**Job Description**:
{job_description}

**Required Skills**: {required_skills}
**Preferred Skills**: {preferred_skills}
**Minimum Experience**: {min_experience_years} years
**Required Languages**: {required_languages}
**Education Requirements**: {education_requirements}

---

**Candidate Profile**:

Name: {candidate_name}
Current Title: {current_title}
Location: {location}
Total Experience: {total_experience_years} years
Skills: {skills}
Languages: {languages}

Experience History:
{experience_details}

Education:
{education_details}

Notable Achievements:
{achievements_details}

Summary: {summary}

---

Return a JSON object with this exact structure:

{
  "skills_score": 0.0-1.0,
  "skills_analysis": {
    "matched_required": ["list of required skills the candidate has"],
    "missing_required": ["list of required skills the candidate lacks"],
    "matched_preferred": ["list of preferred skills the candidate has"],
    "coverage_ratio": 0.0-1.0
  },
  "experience_score": 0.0-1.0,
  "experience_analysis": {
    "relevant_roles": ["role at company — brief relevance note"],
    "years_relevant": number,
    "industry_alignment": "strong | moderate | weak",
    "seniority_fit": "overqualified | match | underqualified"
  },
  "education_score": 0.0-1.0,
  "education_analysis": {
    "degree_match": "exact | related | unrelated",
    "institution_tier": "top | good | standard | unknown",
    "field_relevance": "direct | adjacent | unrelated"
  },
  "language_score": 0.0-1.0,
  "language_analysis": {
    "matched_languages": ["language (level)"],
    "missing_languages": ["language"]
  },
  "overall_match_score": 0-100,
  "reasoning": "2-4 sentence explanation of the overall assessment, highlighting key strengths and gaps. Written for a recruiter audience.",
  "recommendation": "strong_match | good_match | partial_match | weak_match"
}

Scoring guidelines:
- skills_score: 1.0 = all required + preferred skills present, 0.5 = most required skills present, 0.0 = few/no required skills
- experience_score: 1.0 = highly relevant experience exceeding requirements, 0.5 = meets minimum with some relevance, 0.0 = no relevant experience
- education_score: 1.0 = exact match or exceeds requirements, 0.5 = related field/level, 0.0 = unrelated
- language_score: 1.0 = all required languages at required levels, 0.5 = partial coverage, 0.0 = no match
- overall_match_score: weighted combination — this is your holistic assessment as an expert recruiter (0-100 scale)

Be objective. Do not inflate scores. A candidate with 2 years of experience should not score 0.8 on experience if the job requires 5 years.
```

## Usage Notes

### Composite Score Calculation

The CV Ranking Engine combines the semantic similarity score from the Semantic Search API with the LLM evaluation scores:

```python
composite_score = (
    weights["semantic"] * semantic_search_score +      # default 0.30
    weights["skills"] * llm_result["skills_score"] +   # default 0.25
    weights["experience"] * llm_result["experience_score"] +  # default 0.25
    weights["education"] * llm_result["education_score"] +    # default 0.10
    weights["language"] * llm_result["language_score"]        # default 0.10
)
```

### Batch Processing

For ranking N candidates against a job description:
1. Send job description to Semantic Search `/search` endpoint → get top-30 candidates with semantic scores
2. For each candidate, call this prompt with the candidate's structured profile
3. Compute composite score
4. Sort by composite score descending
5. Cache results in `cv_ranking_results` table

### Rate Limiting

LLM calls for ranking are parallelized with configurable concurrency (default: 5). Use `asyncio.Semaphore` to control concurrent API calls and respect Anthropic rate limits.

### Handling Missing Data

If a candidate profile has missing fields (e.g., no education listed), instruct the LLM to score that dimension as 0.0 with a note in the analysis. Do not penalize unknowns beyond the zero score.
