"""Tests for the Gemini context-cache path in LLMClient (extraction prompt).

The cache is an opt-in optimization (GEMINI_CACHE_ENABLED). These tests mock the
google-genai client so no network/API key is needed, and assert: the stable
prefix is cached once and reused, a catalog fingerprint change recreates it,
and any cache failure falls back to the plain (uncached) call. They also assert
the cache-split marker never leaks into the content sent to Gemini.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.catalog_store import catalog_store
from app.services.llm_client import _CACHE_SPLIT_MARKER, LLMClient

_PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
_VALID_JSON = json.dumps({"name": "X", "skills": ["Python"], "experience": [], "education": [],
                          "languages": [], "certifications": [], "achievements": []})


def _gen_response(text: str = _VALID_JSON) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    return resp


def _build_client(*, cache_enabled: bool) -> tuple[LLMClient, MagicMock]:
    with patch("app.services.llm_client.genai.Client", return_value=MagicMock()):
        client = LLMClient(
            provider="gemini", api_key="test", model="gemini-2.5-flash",
            base_url=None, prompts_dir=_PROMPTS,
            cache_enabled=cache_enabled, cache_ttl_seconds=3600,
        )
    gemini = MagicMock()
    gemini.aio.caches.create = AsyncMock(return_value=MagicMock(name="cached_obj"))
    gemini.aio.caches.create.return_value.name = "cachedContents/abc"
    gemini.aio.models.generate_content = AsyncMock(return_value=_gen_response())
    client._gemini = gemini
    return client, gemini


async def _extract(client: LLMClient) -> dict:
    return await client.complete_json(
        prompt_key="cv_entity_extraction",
        variables={"detected_language": "en", "extraction_notes": "clean", "cv_text": "Some CV"},
    )


@pytest.fixture(autouse=True)
def _restore_fingerprint():
    saved = catalog_store._fingerprint
    yield
    catalog_store._fingerprint = saved


@pytest.mark.asyncio
async def test_cache_created_once_and_reused() -> None:
    catalog_store._fingerprint = "fp-1"
    client, gemini = _build_client(cache_enabled=True)

    await _extract(client)
    await _extract(client)

    # Cache built once, reused on the second call.
    assert gemini.aio.caches.create.await_count == 1
    assert gemini.aio.models.generate_content.await_count == 2
    # Generation used the cached handle and a marker-free tail.
    _, kwargs = gemini.aio.models.generate_content.call_args
    assert kwargs["config"].cached_content == "cachedContents/abc"
    assert _CACHE_SPLIT_MARKER not in kwargs["contents"]
    assert "Some CV" in kwargs["contents"]


@pytest.mark.asyncio
async def test_fingerprint_change_recreates_cache() -> None:
    catalog_store._fingerprint = "fp-1"
    client, gemini = _build_client(cache_enabled=True)
    await _extract(client)
    catalog_store._fingerprint = "fp-2"
    await _extract(client)
    assert gemini.aio.caches.create.await_count == 2


@pytest.mark.asyncio
async def test_cache_create_failure_falls_back_to_uncached() -> None:
    catalog_store._fingerprint = "fp-1"
    client, gemini = _build_client(cache_enabled=True)
    gemini.aio.caches.create = AsyncMock(side_effect=RuntimeError("too small to cache"))

    result = await _extract(client)

    assert result["skills"] == ["Python"]
    # Fell back to a single uncached generate call with the full prompt, no cache handle.
    assert gemini.aio.models.generate_content.await_count == 1
    _, kwargs = gemini.aio.models.generate_content.call_args
    assert kwargs["config"].cached_content is None
    assert _CACHE_SPLIT_MARKER not in kwargs["contents"]


@pytest.mark.asyncio
async def test_cache_disabled_strips_marker_no_cache_call() -> None:
    client, gemini = _build_client(cache_enabled=False)
    await _extract(client)
    gemini.aio.caches.create.assert_not_called()
    _, kwargs = gemini.aio.models.generate_content.call_args
    assert _CACHE_SPLIT_MARKER not in kwargs["contents"]
