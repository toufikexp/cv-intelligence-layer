"""Shared test fixtures for the CV Intelligence Layer test suite."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.models.database import CVProfile
from app.models.schemas import CandidateProfile, EducationEntry, ExperienceEntry, LanguageEntry


@pytest.fixture()
def fake_candidate_profile() -> CandidateProfile:
    """Factory for a realistic CandidateProfile."""
    return CandidateProfile(
        name="Jean Dupont",
        email="jean.dupont@example.com",
        phone="+213 555 123 456",
        location="Algiers",
        current_title="Senior Software Engineer",
        summary="Experienced engineer with 8 years in Python and cloud.",
        skills=["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"],
        experience=[
            ExperienceEntry(
                company="Acme Corp",
                role="Senior Developer",
                start_date="2020-01",
                end_date="2024-01",
                description="Led backend team.",
            ),
            ExperienceEntry(
                company="StartupX",
                role="Developer",
                start_date="2016-06",
                end_date="2019-12",
            ),
        ],
        education=[
            EducationEntry(institution="USTHB", degree="Master", field="Computer Science", year="2016"),
        ],
        languages=[
            LanguageEntry(language="French", level="native"),
            LanguageEntry(language="English", level="fluent"),
        ],
        certifications=["AWS Solutions Architect"],
        total_experience_years=8.0,
    )


@pytest.fixture()
def fake_cv_profile(fake_candidate_profile: CandidateProfile) -> CVProfile:
    """Factory for a CVProfile ORM instance (not persisted)."""
    now = datetime.now(timezone.utc)
    return CVProfile(
        cv_id=uuid.uuid4(),
        collection_id=uuid.uuid4(),
        external_id="ext-001",
        file_hash="abc123deadbeef",
        candidate_name=fake_candidate_profile.name,
        email=fake_candidate_profile.email,
        phone=fake_candidate_profile.phone,
        profile_data=fake_candidate_profile.model_dump(mode="json"),
        raw_text="Full CV text here...",
        language="fr",
        extraction_method="text_extraction",
        search_doc_external_id="abc123deadbeef",
        status="ready",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def mock_search_client() -> AsyncMock:
    """Mock SemanticSearchClient with sensible defaults."""
    client = AsyncMock()
    client.search.return_value = {
        "results": [
            {"external_id": "abc123deadbeef", "score": 0.85, "metadata": {}},
        ],
        "total": 1,
    }
    client.ingest_documents.return_value = {"status": "ok", "job_id": str(uuid.uuid4())}
    client.delete_document.return_value = None
    client.delete_document_if_exists.return_value = None
    client.aclose.return_value = None
    return client


@pytest.fixture()
def mock_llm_client() -> AsyncMock:
    """Mock LLMClient that returns structured JSON dicts."""
    client = AsyncMock()

    def _make_response(prompt_key: str = "", **kwargs: Any) -> dict[str, Any]:
        if prompt_key == "cv_entity_extraction":
            return {
                "name": "Jean Dupont",
                "email": "jean@example.com",
                "phone": "0555123456",
                "location": "Algiers",
                "current_title": "Developer",
                "skills": ["Python", "SQL"],
                "experience": [],
                "education": [],
                "languages": [],
            }
        if prompt_key == "cv_ranking":
            return {
                "skills_score": 0.8,
                "experience_score": 0.7,
                "education_score": 0.6,
                "language_score": 0.9,
                "recommendation": "good_match",
                "reasoning": "Strong skills match.",
                "skills_analysis": {"matched_required": ["Python"], "missing_required": []},
            }
        if prompt_key == "answer_scoring":
            return {
                "similarity_score": 0.75,
                "points_awarded": 7.5,
                "accuracy_assessment": "Good",
                "completeness_assessment": "Complete",
                "feedback": "Well answered.",
                "key_concepts": {"covered": ["OOP"], "missed": []},
            }
        return {}

    async def _complete_json(*, prompt_key: str, variables: dict[str, Any]) -> dict[str, Any]:
        return _make_response(prompt_key=prompt_key)

    client.complete_json = _complete_json
    return client
