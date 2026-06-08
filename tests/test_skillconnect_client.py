"""Tests for the SkillConnect catalog HTTP client (no auth, proxy/SSL-aware)."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.services.skillconnect_client import SkillConnectClient, get_skillconnect_client

_BASE = "https://elevate.test/elevate-api"
_PATH = "/api/v1/profile/skill-catalogs"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_skill_catalog_parses_data_envelope() -> None:
    respx.get(f"{_BASE}{_PATH}").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"code": "SK1", "name": "Python", "category": "Tech", "id": 7}]},
        )
    )
    client = SkillConnectClient(base_url=_BASE)
    try:
        rows = await client.fetch_skill_catalog()
    finally:
        await client.aclose()
    assert rows == [{"code": "SK1", "name": "Python", "category": "Tech", "id": 7}]


@respx.mock
@pytest.mark.asyncio
async def test_fetch_skill_catalog_accepts_bare_list() -> None:
    respx.get(f"{_BASE}{_PATH}").mock(
        return_value=httpx.Response(200, json=[{"code": "SK2", "name": "SQL"}])
    )
    client = SkillConnectClient(base_url=_BASE)
    try:
        rows = await client.fetch_skill_catalog()
    finally:
        await client.aclose()
    assert rows == [{"code": "SK2", "name": "SQL"}]


@respx.mock
@pytest.mark.asyncio
async def test_fetch_skill_catalog_retries_then_succeeds() -> None:
    route = respx.get(f"{_BASE}{_PATH}").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"data": [{"code": "SK3", "name": "Go"}]}),
        ]
    )
    client = SkillConnectClient(base_url=_BASE)
    try:
        rows = await client.fetch_skill_catalog()
    finally:
        await client.aclose()
    assert route.call_count == 2
    assert rows == [{"code": "SK3", "name": "Go"}]


def test_get_skillconnect_client_none_without_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "skillconnect_api_base_url", None, raising=False)
    assert get_skillconnect_client() is None
