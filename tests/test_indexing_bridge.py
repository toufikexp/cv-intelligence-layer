"""Tests for the indexing bridge (CandidateProfile → Search document)."""

from __future__ import annotations

from app.models.schemas import CandidateProfile, EducationEntry
from app.services.indexing_bridge import build_search_document


def test_build_search_document_content(fake_candidate_profile: CandidateProfile) -> None:
    doc = build_search_document(external_id="hash123", profile=fake_candidate_profile, language="fr")

    assert doc.external_id == "hash123"
    assert "Jean Dupont" in doc.content
    assert "Python" in doc.content
    assert "Acme Corp" in doc.content


def test_build_search_document_metadata(fake_candidate_profile: CandidateProfile) -> None:
    doc = build_search_document(external_id="hash123", profile=fake_candidate_profile, language="fr")

    assert doc.metadata["skills"] == fake_candidate_profile.skills
    assert doc.metadata["experience_years"] == 8
    assert doc.metadata["language"] == "fr"
    assert doc.metadata["location"] == "Algiers"


def test_build_search_document_minimal() -> None:
    profile = CandidateProfile(name="Minimal User")
    doc = build_search_document(external_id="min_hash", profile=profile, language=None)

    assert doc.external_id == "min_hash"
    assert "Minimal User" in doc.content
    assert doc.metadata["language"] == "mixed"
    assert doc.metadata["experience_years"] == 0


def test_build_search_document_education_level() -> None:
    profile = CandidateProfile(
        name="Edu User",
        education=[EducationEntry(institution="MIT", degree="PhD", field="CS")],
    )
    doc = build_search_document(external_id="edu_hash", profile=profile, language="en")

    assert doc.metadata.get("education_level") == "phd"
