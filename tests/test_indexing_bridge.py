"""Tests for the indexing bridge (CandidateProfile + raw_text → Search document)."""

from __future__ import annotations

from app.models.schemas import (
    AchievementEntry,
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
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
    # content must be the raw CV text (stripped), not the formatted projection
    assert doc.content == RAW_CV_TEXT.strip()


def test_build_search_document_metadata(fake_candidate_profile: CandidateProfile) -> None:
    doc = build_search_document(
        external_id="ext-1",
        profile=fake_candidate_profile,
        raw_text=RAW_CV_TEXT,
        language="fr",
    )

    assert doc.metadata["skills"] == fake_candidate_profile.skills
    assert doc.metadata["experience_years"] == 8
    assert doc.metadata["language"] == "fr"
    assert doc.metadata["location"] == "Algiers"


def test_build_search_document_minimal_uses_raw_text() -> None:
    profile = CandidateProfile(name="Minimal User")
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
    # Defensive: Semantic Search rejects empty content, so the bridge should
    # fall back to profile.summary / profile.name when raw_text is empty.
    profile = CandidateProfile(name="Fallback User", summary="A short summary")
    doc = build_search_document(
        external_id="ext-empty",
        profile=profile,
        raw_text="",
        language="en",
    )

    assert doc.content == "A short summary"


def test_build_search_document_education_level() -> None:
    profile = CandidateProfile(
        name="Edu User",
        education=[EducationEntry(institution="MIT", degree="PhD", field="CS")],
    )
    doc = build_search_document(
        external_id="ext-edu",
        profile=profile,
        raw_text="PhD in CS at MIT",
        language="en",
    )

    assert doc.metadata.get("education_level") == "phd"


# ---------------------------------------------------------------------------
# build_synthetic_text
# ---------------------------------------------------------------------------


def test_build_synthetic_text_full_profile() -> None:
    profile = CandidateProfile(
        name="Jean Dupont",
        current_title="Senior Data Engineer",
        location="Algiers",
        email="jean@example.com",
        phone="+213555123456",
        summary="8 years experience in data engineering.",
        skills=["Python", "Spark", "PostgreSQL"],
        experience=[
            ExperienceEntry(
                company="Acme Corp",
                role="Senior Developer",
                start_date="2020-01",
                end_date="2024-01",
                description="Led backend team.",
            ),
        ],
        education=[
            EducationEntry(institution="USTHB", degree="Master", field="CS", year="2016"),
        ],
        languages=[
            LanguageEntry(language="French", level="native"),
            LanguageEntry(language="English", level="fluent"),
        ],
        certifications=["AWS Solutions Architect"],
        achievements=[
            AchievementEntry(title="Data Lake Migration", year="2023", description="Migrated to AWS S3"),
        ],
    )
    text = build_synthetic_text(profile)

    assert "Name: Jean Dupont" in text
    assert "Title: Senior Data Engineer" in text
    assert "Location: Algiers" in text
    assert "Skills: Python, Spark, PostgreSQL" in text
    assert "Senior Developer @ Acme Corp" in text
    assert "Master CS — USTHB (2016)" in text
    assert "French (native)" in text
    assert "AWS Solutions Architect" in text
    assert "Data Lake Migration (2023): Migrated to AWS S3" in text


def test_build_synthetic_text_minimal_profile() -> None:
    profile = CandidateProfile(name="Minimal User")
    text = build_synthetic_text(profile)
    assert text == "Name: Minimal User"


def test_build_synthetic_text_deterministic() -> None:
    profile = CandidateProfile(name="Same", skills=["A", "B"])
    assert build_synthetic_text(profile) == build_synthetic_text(profile)
