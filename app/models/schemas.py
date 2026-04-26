from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str
    code: str


CVStatusEnum = Literal[
    "pending", "extracting", "ocr_processing", "entity_extraction",
    "indexing", "ready", "failed", "index_failed",
]


class ExperienceEntry(BaseModel):
    company: str
    role: str
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    location: str | None = None


class EducationEntry(BaseModel):
    institution: str
    degree: str | None = None
    field: str | None = None
    year: str | None = None


LanguageLevel = Literal["native", "fluent", "advanced", "intermediate", "beginner"]


class LanguageEntry(BaseModel):
    language: str
    level: LanguageLevel


class AchievementEntry(BaseModel):
    """A discrete project, realization, or notable accomplishment.

    Distinct from ``ExperienceEntry``: an achievement is a named deliverable
    (e.g. "Migration Data Lake vers AWS") rather than a job tenure.
    """

    title: str
    year: str | None = None
    description: str | None = None


class CandidateProfile(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    current_title: str | None = None
    summary: str | None = None
    linkedin_url: AnyHttpUrl | None = None
    github_url: AnyHttpUrl | None = None
    portfolio_url: AnyHttpUrl | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    languages: list[LanguageEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    achievements: list[AchievementEntry] = Field(default_factory=list)
    total_experience_years: float | None = None


class CandidateProfilePatch(BaseModel):
    """Partial CandidateProfile for PATCH requests.

    Every field is optional. Scalars are replaced when provided; list fields
    are replaced wholesale (not merged element-wise). Unknown fields are
    rejected so typos surface as 422 rather than being silently dropped.
    Use ``model_dump(exclude_unset=True)`` at the merge site so omitted
    fields leave the stored value untouched.
    """

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    current_title: str | None = None
    summary: str | None = None
    linkedin_url: AnyHttpUrl | None = None
    github_url: AnyHttpUrl | None = None
    portfolio_url: AnyHttpUrl | None = None
    skills: list[str] | None = None
    experience: list[ExperienceEntry] | None = None
    education: list[EducationEntry] | None = None
    languages: list[LanguageEntry] | None = None
    certifications: list[str] | None = None
    achievements: list[AchievementEntry] | None = None
    total_experience_years: float | None = None

    model_config = {"extra": "forbid"}


class CandidateCreateRequest(BaseModel):
    """Create a candidate profile from structured JSON (no CV document)."""

    collection_id: uuid.UUID
    external_id: str = Field(min_length=1, max_length=255)
    profile: CandidateProfile
    callback_url: str | None = None

    model_config = {"extra": "forbid"}


class CVUploadResponse(BaseModel):
    cv_id: uuid.UUID
    job_id: uuid.UUID
    status: Literal["pending", "extracting", "indexing", "ready", "failed", "index_failed"] = "pending"
    file_hash: str | None = None
    no_change: bool = False


class CVDuplicateResponse(BaseModel):
    cv_id: uuid.UUID
    message: str


class CVProfileResponse(BaseModel):
    cv_id: uuid.UUID
    external_id: str | None = None
    collection_id: uuid.UUID
    status: Literal["pending", "extracting", "indexing", "ready", "failed", "index_failed"]
    language: str | None = None
    extraction_method: str | None = None
    profile: CandidateProfile | None = None
    created_at: datetime
    updated_at: datetime | None = None


class CVStatusResponse(BaseModel):
    cv_id: uuid.UUID
    status: CVStatusEnum
    current_stage: str | None = None
    error_message: str | None = None
    progress_pct: int | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class CVSearchRequest(BaseModel):
    collection_id: uuid.UUID
    query: str = Field(min_length=1)
    filters: dict[str, Any] | None = None
    limit: int = Field(default=20, le=100)
    offset: int = Field(default=0, ge=0)
    facets: list[str] | None = None


class CVSearchResult(BaseModel):
    cv_id: uuid.UUID | None = None
    external_id: str | None = None
    score: float | None = None
    candidate_name: str | None = None
    current_title: str | None = None
    location: str | None = None
    skills: list[str] | None = None
    experience_years: float | None = None
    highlights: list[str] | None = None


class CVSearchResponse(BaseModel):
    results: list[CVSearchResult]
    facets: dict[str, Any] | None = None
    total: int
    query_id: uuid.UUID
    took_ms: int


class RankingWeights(BaseModel):
    semantic: float | None = None
    skills: float | None = None
    experience: float | None = None
    education: float | None = None
    language: float | None = None


class RankingRequest(BaseModel):
    collection_id: uuid.UUID
    job_description: str
    required_skills: list[str] | None = None
    preferred_skills: list[str] | None = None
    min_experience_years: int = 0
    required_languages: list[str] | None = None
    education_requirements: str | None = None
    recall_size: int = Field(default=30, le=100)
    weights: RankingWeights | None = None


RecommendationEnum = Literal["strong_match", "good_match", "partial_match", "weak_match"]


class SkillsAnalysis(BaseModel):
    matched_required: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)


class RankedCandidate(BaseModel):
    cv_id: uuid.UUID
    external_id: str | None = None
    score: float
    recommendation: RecommendationEnum
    reasoning: str
    skills_analysis: SkillsAnalysis | None = None


class RankingResponse(BaseModel):
    results: list[RankedCandidate]
    job_id: uuid.UUID
    took_ms: int


class AsyncJobResponse(BaseModel):
    job_id: uuid.UUID
    status: str = "processing"


QuestionType = Literal["factual", "conceptual", "analytical", "technical", "open_ended"]


class AnswerQuestion(BaseModel):
    question_id: str
    question_text: str
    question_type: QuestionType = "conceptual"
    reference_answer: str
    candidate_answer: str
    max_points: float = 10
    grading_rubric: str | None = None


class AnswerScoringRequest(BaseModel):
    collection_id: uuid.UUID
    cv_id: uuid.UUID | None = None
    questions: list[AnswerQuestion]
    use_llm_grading: bool = True


ScoringMethod = Literal["embedding", "llm", "hybrid"]


class KeyConcepts(BaseModel):
    covered: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list)


class AnswerScore(BaseModel):
    question_id: str
    similarity_score: float
    points_awarded: float
    max_points: float
    scoring_method: ScoringMethod
    accuracy_assessment: str | None = None
    completeness_assessment: str | None = None
    feedback: str | None = None
    key_concepts: KeyConcepts | None = None


class AnswerScoringResponse(BaseModel):
    results: list[AnswerScore]
    total_score: float
    max_score: float
    score_percentage: float | None = None
    cv_id: uuid.UUID | None = None


class CollectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    language: str = "auto"


class CollectionCreateResponse(BaseModel):
    id: uuid.UUID
    name: str | None = None
    status: str | None = None
    created_at: datetime | None = None


class CollectionListResponse(BaseModel):
    collections: list[CollectionCreateResponse]
    total: int | None = None


# ---------------------------------------------------------------------------
# Webhook schemas
# ---------------------------------------------------------------------------

IngestionDocStatus = Literal["indexed", "failed"]
IngestionJobStatus = Literal["completed", "completed_with_errors"]


class IngestedDocumentResult(BaseModel):
    external_id: str
    status: IngestionDocStatus
    error: str | None = None


class IngestionWebhookPayload(BaseModel):
    """Incoming webhook from Semantic Search after document ingest completes."""

    event: str
    job_id: uuid.UUID
    collection_id: uuid.UUID
    status: IngestionJobStatus
    total_docs: int
    processed_docs: int
    failed_docs: int
    documents: list[IngestedDocumentResult]
    completed_at: datetime


class HPCallbackPayload(BaseModel):
    """Outgoing webhook to Hiring Platform when CV processing finishes."""

    external_id: str | None = None
    file_hash: str | None = None
    status: Literal["ready", "index_failed"]
    error: str | None = None
    completed_at: datetime

