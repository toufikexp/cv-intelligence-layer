"""Shared test fixtures for the CV Intelligence Layer test suite."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.models.database import CVProfile
from app.models.schemas import (
    CandidateProfile,
    EducationEntry,
    EmployeeInfo,
    ExperienceEntry,
    LanguageEntry,
    SkillEntry,
)


# Skill codes used across the test suite. The catalog is identity-mapped
# (code == name) so code↔name resolution exercises the real lookup path while
# keeping assertions readable. Real code≠name resolution is covered by
# test_catalog_store / the resolution test in test_entity_extractor.
TEST_SKILL_NAMES = [
    "Python", "FastAPI", "PostgreSQL", "Docker", "AWS", "SQL",
    "Spark", "Airflow", "Java", "A", "B",
]


@pytest.fixture(autouse=True)
def seed_catalog_store():
    """Populate the process-wide catalog_store with identity-mapped test skills.

    Skills are stored as codes; indexing/ranking/search resolve code→name from
    the catalog. This fixture makes that resolution work in unit tests without a
    live DB, and restores the store afterwards so tests stay isolated.
    """
    from app.services.catalog_store import catalog_store, normalize

    saved = (
        catalog_store._skill_code_to_name,
        catalog_store._skill_norm_to_code,
    )
    catalog_store._skill_code_to_name = {n: n for n in TEST_SKILL_NAMES}
    catalog_store._skill_norm_to_code = {normalize(n): n for n in TEST_SKILL_NAMES}
    try:
        yield
    finally:
        (
            catalog_store._skill_code_to_name,
            catalog_store._skill_norm_to_code,
        ) = saved


@pytest.fixture()
def fake_candidate_profile() -> CandidateProfile:
    """Factory for a realistic CandidateProfile."""
    return CandidateProfile(
        summary="Experienced engineer with 8 years in Python and cloud.",
        employee=EmployeeInfo(
            firstname="Jean",
            lastname="Dupont",
            email="jean.dupont@example.com",
            phone="+213 555 123 456",
            function="Senior Software Engineer",
            region="Algiers",
        ),
        skills=[
            SkillEntry(skill="Python", score="ADVANCED"),
            SkillEntry(skill="FastAPI", score="ADVANCED"),
            SkillEntry(skill="PostgreSQL", score="INTERMEDIATE"),
            SkillEntry(skill="Docker", score="INTERMEDIATE"),
            SkillEntry(skill="AWS", score="INTERMEDIATE"),
        ],
        experiences=[
            ExperienceEntry(
                company="Acme Corp",
                role="Senior Developer",
                startDate="2020-01",
                endDate="2024-01",
                description="Led backend team.",
            ),
            ExperienceEntry(
                company="StartupX",
                role="Developer",
                startDate="2016-06",
                endDate="2019-12",
            ),
        ],
        educations=[
            EducationEntry(
                institution="université",
                establishment="USTHB", typeEducation="MASTER",
                fieldOfStudy="Computer Science", dateGraduation="2016",
            ),
        ],
        languages=[
            LanguageEntry(language="French", proficiency="NATIVE"),
            LanguageEntry(language="English", proficiency="C1"),
        ],
        certifications=[],
    )


@pytest.fixture()
def fake_cv_profile(fake_candidate_profile: CandidateProfile) -> CVProfile:
    """Factory for a CVProfile ORM instance (not persisted)."""
    now = datetime.now(timezone.utc)
    emp = fake_candidate_profile.employee
    return CVProfile(
        cv_id=uuid.uuid4(),
        collection_id=uuid.uuid4(),
        external_id="ext-001",
        file_hash="abc123deadbeef",
        candidate_name=f"{emp.firstname} {emp.lastname}" if emp else None,
        email=emp.email if emp else None,
        phone=emp.phone if emp else None,
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
                "summary": "Experienced developer.",
                "function": "Developer",
                "skills": [{"name": "Python", "score": "ADVANCED"}, {"name": "SQL", "score": "INTERMEDIATE"}],
                "experiences": [],
                "educations": [],
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

    async def _complete_json(
        *, prompt_key: str, variables: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return _make_response(prompt_key=prompt_key)

    client.complete_json = _complete_json
    return client
