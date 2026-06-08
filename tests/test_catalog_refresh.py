"""Tests for catalog refresh orchestration (fail-soft, fingerprint signal)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.catalog_refresh as refresh_mod


def _patch_session():
    """Patch _make_session to yield a no-op engine + session factory."""
    engine = MagicMock()
    engine.dispose = AsyncMock()
    fake_db = AsyncMock()

    @asynccontextmanager
    async def _session_ctx():
        yield fake_db

    session_factory = MagicMock(side_effect=lambda: _session_ctx())
    return patch.object(refresh_mod, "_make_session", return_value=(engine, session_factory))


@pytest.mark.asyncio
async def test_refresh_loads_db_only_when_fetch_disabled() -> None:
    store = MagicMock()
    store.load_from_db = AsyncMock()
    store.refresh_skills_from_api = AsyncMock()
    with _patch_session(), patch.object(refresh_mod, "catalog_store", store):
        changed = await refresh_mod.refresh_catalog(fetch_api=False)
    assert changed is False
    store.load_from_db.assert_awaited_once()
    store.refresh_skills_from_api.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_failsoft_when_api_errors() -> None:
    store = MagicMock()
    store.load_from_db = AsyncMock()
    store.refresh_skills_from_api = AsyncMock()
    store.skill_count = 0

    client = MagicMock()
    client.fetch_skill_catalog = AsyncMock(side_effect=RuntimeError("proxy blocked"))
    client.aclose = AsyncMock()

    with (
        _patch_session(),
        patch.object(refresh_mod, "catalog_store", store),
        patch.object(refresh_mod, "get_skillconnect_client", return_value=client),
    ):
        # Must NOT raise — last-known DB copy already loaded.
        changed = await refresh_mod.refresh_catalog(fetch_api=True)

    assert changed is False
    store.load_from_db.assert_awaited()  # served last-known
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_reports_fingerprint_change() -> None:
    store = MagicMock()
    store.load_from_db = AsyncMock()
    store.refresh_skills_from_api = AsyncMock(return_value=True)
    store.skill_count = 5

    client = MagicMock()
    client.fetch_skill_catalog = AsyncMock(return_value=[{"code": "SK1", "name": "Python"}])
    client.aclose = AsyncMock()

    with (
        _patch_session(),
        patch.object(refresh_mod, "catalog_store", store),
        patch.object(refresh_mod, "get_skillconnect_client", return_value=client),
    ):
        changed = await refresh_mod.refresh_catalog(fetch_api=True)

    assert changed is True
    store.refresh_skills_from_api.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_noop_when_no_client_configured() -> None:
    store = MagicMock()
    store.load_from_db = AsyncMock()
    store.refresh_skills_from_api = AsyncMock()
    with (
        _patch_session(),
        patch.object(refresh_mod, "catalog_store", store),
        patch.object(refresh_mod, "get_skillconnect_client", return_value=None),
    ):
        changed = await refresh_mod.refresh_catalog(fetch_api=True)
    assert changed is False
    store.refresh_skills_from_api.assert_not_called()
