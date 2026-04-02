from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth import get_api_key
from app.models.schemas import CollectionCreateRequest, CollectionCreateResponse, CollectionListResponse
from app.services.search_client import get_search_client

router = APIRouter()


@router.post("/collections", status_code=201, response_model=CollectionCreateResponse)
async def create_collection(
    req: CollectionCreateRequest,
    _: str = Depends(get_api_key),
) -> CollectionCreateResponse:
    client = get_search_client()
    try:
        resp = await client.create_collection({"name": req.name, "description": req.description, "language": req.language})
    finally:
        await client.aclose()
    return CollectionCreateResponse.model_validate(resp, strict=False)


@router.get("/collections", response_model=CollectionListResponse)
async def list_collections(
    limit: int = 20,
    offset: int = 0,
    _: str = Depends(get_api_key),
) -> CollectionListResponse:
    client = get_search_client()
    try:
        resp = await client.list_collections(limit=limit, offset=offset)
    finally:
        await client.aclose()
    # passthrough
    return CollectionListResponse.model_validate(resp, strict=False)

