"""Tests for the Semantic Search API HTTP client."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from app.services.search_client import SemanticSearchClient


@pytest.fixture()
def client() -> SemanticSearchClient:
    return SemanticSearchClient(base_url="http://test-search:8000", api_key="test-key")


@respx.mock
@pytest.mark.asyncio
async def test_search(client: SemanticSearchClient) -> None:
    cid = uuid.uuid4()
    respx.post(f"http://test-search:8000/api/v1/collections/{cid}/search").mock(
        return_value=httpx.Response(200, json={"results": [{"external_id": "doc1", "score": 0.9}], "total": 1})
    )

    result = await client.search(collection_id=cid, query="python developer")
    assert result["total"] == 1
    assert result["results"][0]["score"] == 0.9


@respx.mock
@pytest.mark.asyncio
async def test_ingest_documents(client: SemanticSearchClient) -> None:
    cid = uuid.uuid4()
    respx.post(f"http://test-search:8000/api/v1/collections/{cid}/documents").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )

    result = await client.ingest_documents(
        collection_id=cid,
        documents=[{"external_id": "doc1", "content": "test", "metadata": {}}],
        upsert=True,
    )
    assert result["status"] == "ok"


@respx.mock
@pytest.mark.asyncio
async def test_delete_document(client: SemanticSearchClient) -> None:
    cid = uuid.uuid4()
    respx.delete(f"http://test-search:8000/api/v1/collections/{cid}/documents/doc1").mock(
        return_value=httpx.Response(204)
    )

    await client.delete_document(collection_id=cid, external_id="doc1")


@respx.mock
@pytest.mark.asyncio
async def test_delete_document_if_exists_404(client: SemanticSearchClient) -> None:
    cid = uuid.uuid4()
    respx.delete(f"http://test-search:8000/api/v1/collections/{cid}/documents/gone").mock(
        return_value=httpx.Response(404)
    )

    # Should not raise
    await client.delete_document_if_exists(collection_id=cid, external_id="gone")


@respx.mock
@pytest.mark.asyncio
async def test_get_document(client: SemanticSearchClient) -> None:
    cid = uuid.uuid4()
    respx.get(f"http://test-search:8000/api/v1/collections/{cid}/documents/doc1").mock(
        return_value=httpx.Response(200, json={"external_id": "doc1", "content": "test"})
    )

    result = await client.get_document(collection_id=cid, external_id="doc1")
    assert result["external_id"] == "doc1"


@respx.mock
@pytest.mark.asyncio
async def test_suggest(client: SemanticSearchClient) -> None:
    cid = uuid.uuid4()
    respx.post(f"http://test-search:8000/api/v1/collections/{cid}/suggest").mock(
        return_value=httpx.Response(200, json={"suggestions": ["Python", "PostgreSQL"]})
    )

    result = await client.suggest(collection_id=cid, prefix="Py")
    assert "suggestions" in result
