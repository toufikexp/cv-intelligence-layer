from __future__ import annotations

import ssl
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings


def _insecure_ssl_context() -> ssl.SSLContext:
    """SSL context for the SkillConnect host's legacy TLS.

    Skips certificate verification AND lowers the OpenSSL security level to 1.
    The Ooredoo ``elevate`` endpoint negotiates a weak (<2048-bit) Diffie-Hellman
    key that OpenSSL 3's default security level 2 rejects with
    ``DH_KEY_TOO_SMALL``; ``SECLEVEL=1`` accepts it. Scoped to this client only.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    return ctx


class SkillConnectClient:
    """HTTP client for the SkillConnect (Ooredoo HR) catalog API.

    The catalog endpoint is an unauthenticated GET. ``elevate.ooredoo.dz`` is an
    INTERNAL host, reachable directly, so this client sets ``trust_env=False`` to
    ignore the ambient ``HTTPS_PROXY`` and connect directly — the corporate
    internet proxy cannot reach this internal host and times out its TLS
    handshake. (httpx defaults ``trust_env`` to True, so it must be disabled
    explicitly; merely omitting it still routes through the env proxy.) An
    explicit ``SKILLCONNECT_PROXY`` may still be set if a future deployment needs
    one. The SSL-verification toggle mirrors the ``LLM_SSL_VERIFY`` pattern.
    """

    def __init__(
        self,
        *,
        base_url: str,
        ssl_verify: bool = True,
        proxy: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        verify: bool | ssl.SSLContext = _insecure_ssl_context() if not ssl_verify else True
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(30.0),
            trust_env=False,
            verify=verify,
            proxy=proxy,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def fetch_skill_catalog(self) -> list[dict[str, Any]]:
        """GET the skill catalog. Returns the list under ``data`` (or a bare list)."""
        resp = await self._client.get("/api/v1/profile/skill-catalogs")
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict):
            data = body.get("data")
            return list(data) if isinstance(data, list) else []
        return list(body) if isinstance(body, list) else []


def get_skillconnect_client() -> SkillConnectClient | None:
    """Build a client from settings, or ``None`` when no base URL is configured."""
    settings = get_settings()
    if not settings.skillconnect_api_base_url:
        return None
    return SkillConnectClient(
        base_url=settings.skillconnect_api_base_url,
        ssl_verify=settings.skillconnect_ssl_verify,
        proxy=settings.skillconnect_proxy,
    )
