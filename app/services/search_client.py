from __future__ import annotations

import uuid
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings


class SemanticSearchClient:
    """HTTP client for the Semantic Search as a Service API."""

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=httpx.Timeout(30.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def create_collection(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client.post("/api/v1/collections", json=payload)
        resp.raise_for_status()
        return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def list_collections(self, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        resp = await self._client.get("/api/v1/collections", params={"limit": limit, "offset": offset})
        resp.raise_for_status()
        return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def ingest_documents(
        self,
        *,
        collection_id: uuid.UUID,
        documents: list[dict[str, Any]],
        upsert: bool = True,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/v1/collections/{collection_id}/documents",
            json={"documents": documents, "upsert": upsert},
        )
        resp.raise_for_status()
        return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def search(
        self,
        *,
        collection_id: uuid.UUID,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        offset: int = 0,
        facets: list[str] | None = None,
        mode: str = "hybrid",
        rerank: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query,
            "mode": mode,
            "rerank": rerank,
            "limit": limit,
            "offset": offset,
        }
        if filters is not None:
            payload["filters"] = filters
        if facets is not None:
            payload["facets"] = facets
        resp = await self._client.post(f"/api/v1/collections/{collection_id}/search", json=payload)
        resp.raise_for_status()
        return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def suggest(self, *, collection_id: uuid.UUID, prefix: str, limit: int = 10) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/v1/collections/{collection_id}/suggest",
            json={"prefix": prefix, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def get_document(self, *, collection_id: uuid.UUID, external_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/api/v1/collections/{collection_id}/documents/{external_id}")
        resp.raise_for_status()
        return resp.json()

    async def delete_document(self, *, collection_id: uuid.UUID, external_id: str) -> None:
        resp = await self._client.delete(f"/api/v1/collections/{collection_id}/documents/{external_id}")
        resp.raise_for_status()

    async def delete_document_if_exists(self, *, collection_id: uuid.UUID, external_id: str) -> None:
        """Delete indexed document; ignore 404 (already removed)."""
        resp = await self._client.delete(f"/api/v1/collections/{collection_id}/documents/{external_id}")
        if resp.status_code == 404:
            return
        resp.raise_for_status()


def get_search_client() -> SemanticSearchClient:
    """Client for Semantic Search read/search operations (Bearer = search API key)."""
    settings = get_settings()
    return SemanticSearchClient(base_url=settings.search_api_base_url, api_key=settings.search_api_key)


def get_ingest_search_client() -> SemanticSearchClient:
    """Client for document ingest/delete (Bearer = ingest API key when configured)."""
    settings = get_settings()
    key = settings.search_ingest_api_key or settings.search_api_key
    return SemanticSearchClient(base_url=settings.search_api_base_url, api_key=key)

