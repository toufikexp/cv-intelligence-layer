from __future__ import annotations

import asyncio
import logging

from app.services.catalog_store import catalog_store
from app.services.skillconnect_client import get_skillconnect_client

logger = logging.getLogger("cv_layer.catalog")


def _make_session() -> tuple:
    """Fresh async engine + session factory (safe after a Celery fork)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.config import get_settings

    eng = create_async_engine(get_settings().database_url)
    return eng, async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)


async def refresh_catalog(*, fetch_api: bool) -> bool:
    """Load catalogs from DB; optionally refresh skills from the SkillConnect API.

    Fail-soft: any API/proxy failure is swallowed after loading the last-known
    DB copy, so startup never crashes on a catalog problem. Returns True if the
    skills fingerprint changed.
    """
    eng, Session = _make_session()
    changed = False
    try:
        async with Session() as db:
            await catalog_store.load_from_db(db)
            if fetch_api:
                client = get_skillconnect_client()
                if client is not None:
                    try:
                        rows = await client.fetch_skill_catalog()
                        changed = await catalog_store.refresh_skills_from_api(db, rows)
                        logger.info(
                            "SkillConnect catalog refreshed (%d skills, changed=%s)",
                            catalog_store.skill_count,
                            changed,
                        )
                    except Exception as exc:
                        logger.warning("SkillConnect catalog refresh failed (serving last-known): %r", exc)
                    finally:
                        await client.aclose()
    finally:
        await eng.dispose()
    return changed


async def periodic_refresh_loop(interval_seconds: int) -> None:
    """Background loop: refresh the skills catalog from the API every interval."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await refresh_catalog(fetch_api=True)
        except Exception as exc:
            logger.warning("Periodic catalog refresh errored: %s", exc)
