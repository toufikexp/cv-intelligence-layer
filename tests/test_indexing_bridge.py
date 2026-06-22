"""Tests for the indexing bridge (CandidateProfile + raw_text → Search document)."""

from __future__ import annotations

from app.models.schemas import (
    AchievementEntry,
    CandidateProfile,
    CertificationEntry,
    EducationEntry,
    EmployeeInfo,
    ExperienceEntry,
    LanguageEntry,
    SkillEntry,
)
from app.services.indexing_bridge import build_search_document, build_synthetic_text


RAW_CV_TEXT = (
    "Jean Dupont\n"
    "Senior Data Engineer — Acme Corp\n"
    "Experienced with Python, Spark, PostgreSQL. Built ETL pipelines and "
    "a customer 360 datamart at Acme Corp between 2020 and 2024."
)


def test_build_search_document_content_is_raw_text(
    fake_candidate_profile: CandidateProfile,
) -> None:
    doc = build_search_document(
        external_id="ext-1",
        profile=fake_candidate_profile,
        raw_text=RAW_CV_TEXT,
        language="fr",
    )

    assert doc.external_id == "ext-1"
    assert doc.content == RAW_CV_TEXT.strip()


def test_build_search_document_metadata(fake_candidate_profile: CandidateProfile) -> None:
    doc = build_search_document(
        external_id="ext-1",
        profile=fake_candidate_profile,
        raw_text=RAW_CV_TEXT,
        language="fr",
    )

    # SS receives skill NAMES, never codes
    assert doc.metadata["skills"] == ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"]
    assert doc.metadata["experience_years"] == 7
    assert doc.metadata["language"] == "fr"
    assert doc.metadata["location"] == "Algiers"


def test_build_search_document_minimal_uses_raw_text() -> None:
    profile = CandidateProfile()
    doc = build_search_document(
        external_id="ext-min",
        profile=profile,
        raw_text="raw body content goes here",
        language=None,
    )

    assert doc.external_id == "ext-min"
    assert doc.content == "raw body content goes here"
    assert doc.metadata["language"] == "mixed"
    assert doc.metadata["experience_years"] == 0


def test_build_search_document_empty_raw_text_falls_back_to_profile() -> None:
    profile = CandidateProfile(summary="A short summary")
    doc = build_search_document(
        external_id="ext-empty",
        profile=profile,
        raw_text="",
        language="en",
    )

    assert doc.content == "A short summary"


def test_build_search_document_education_level() -> None:
    profile = CandidateProfile(
        educations=[
            EducationEntry(establishment="MIT", typeEducation="DOCTORAT", fieldOfStudy="CS"),
        ],
    )
    doc = build_search_document(
        external_id="ext-edu",
        profile=profile,
        raw_text="PhD in CS at MIT",
        language="en",
    )

    assert doc.metadata.get("education_level") == "doctorat"


# ---------------------------------------------------------------------------
# build_synthetic_text
# ---------------------------------------------------------------------------


def test_build_synthetic_text_full_profile() -> None:
    profile = CandidateProfile(
        employee=EmployeeInfo(
            firstname="Jean",
            lastname="Dupont",
            email="jean@example.com",
            phone="+213555123456",
            function="Senior Data Engineer",
            region="Algiers",
        ),
        summary="8 years experience in data engineering.",
        skills=[
            SkillEntry(skill="Python"),
            SkillEntry(skill="Spark"),
            SkillEntry(skill="PostgreSQL"),
        ],
        experiences=[
            ExperienceEntry(
                company="Acme Corp",
                role="Senior Developer",
                startDate="2020-01",
                endDate="2024-01",
                description="Led backend team.",
            ),
        ],
        educations=[
            EducationEntry(
                establishment="USTHB",
                typeEducation="MASTER",
                fieldOfStudy="CS",
                dateGraduation="2016",
            ),
        ],
        languages=[
            LanguageEntry(language="French", proficiency="NATIVE"),
            LanguageEntry(language="English", proficiency="C1"),
        ],
        certifications=[CertificationEntry(title="AWS Solutions Architect")],
        achievements=[
            AchievementEntry(
                title="Data Lake Migration",
                startDate="2023",
                description="Migrated to AWS S3",
            ),
        ],
    )
    text = build_synthetic_text(profile)

    assert "Name: Jean Dupont" in text
    assert "Title: Senior Data Engineer" in text
    assert "Location: Algiers" in text
    assert "Skills: Python, Spark, PostgreSQL" in text
    assert "Senior Developer @ Acme Corp" in text
    assert "MASTER CS — USTHB (2016)" in text
    assert "French (NATIVE)" in text
    assert "AWS Solutions Architect" in text
    assert "Data Lake Migration (2023): Migrated to AWS S3" in text


def test_build_synthetic_text_minimal_profile() -> None:
    profile = CandidateProfile()
    text = build_synthetic_text(profile)
    assert text == ""


def test_build_synthetic_text_with_name_only() -> None:
    profile = CandidateProfile(
        employee=EmployeeInfo(firstname="Minimal", lastname="User"),
    )
    text = build_synthetic_text(profile)
    assert text == "Name: Minimal User"


def test_build_synthetic_text_deterministic() -> None:
    profile = CandidateProfile(
        skills=[SkillEntry(skill="A"), SkillEntry(skill="B")],
    )
    assert build_synthetic_text(profile) == build_synthetic_text(profile)
