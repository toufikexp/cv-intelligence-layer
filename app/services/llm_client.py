from __future__ import annotations

import json
import re
import ssl
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings
from app.services.prompt_loader import PromptBundle, load_prompt
from app.utils.metrics import llm_duration_seconds, llm_errors_total


def _insecure_ssl_context() -> ssl.SSLContext:
    """Return an SSL context that skips certificate verification."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _parse_json_from_llm(text: str) -> dict[str, Any]:
    """Parse JSON from model output; strip optional markdown fences."""
    t = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL | re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    return json.loads(t)


# Marker in the extraction template separating the stable prefix (instructions,
# schema, rules, skills vocabulary) from the per-CV variable tail. The stable
# prefix is what gets cached in Gemini context cache.
_CACHE_SPLIT_MARKER = "<<<CV_INPUT>>>"
_EXTRACTION_PROMPT_KEY = "cv_entity_extraction"


class LLMClient:
    """LLM wrapper: Gemini via `google-genai` (default); OpenAI-compatible HTTP for local LLM."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        model: str,
        base_url: str | None,
        prompts_dir: Path,
        ssl_verify: bool = True,
        cache_enabled: bool = False,
        cache_ttl_seconds: int = 3600,
    ) -> None:
        self._provider = provider.lower().strip()
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._ssl_verify = ssl_verify
        # Gemini context cache (extraction prompt prefix). In-process per client:
        # each worker/api process lazily creates its own cache and recreates it
        # when the catalog fingerprint changes or the TTL lapses. Fail-soft —
        # any cache error falls back to the plain (uncached) call.
        self._cache_enabled = cache_enabled
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache_name: str | None = None
        self._cache_fingerprint: str | None = None
        self._cache_expires_at: float = 0.0
        self._prompts: dict[str, PromptBundle] = {
            "cv_entity_extraction": load_prompt(prompts_dir / "cv_entity_extraction.md"),
            "cv_ranking": load_prompt(prompts_dir / "cv_ranking.md"),
            "answer_scoring": load_prompt(prompts_dir / "answer_scoring.md"),
        }
        self._gemini: genai.Client | None = None
        if self._provider == "gemini":
            kwargs: dict[str, Any] = {}
            if api_key:
                kwargs["api_key"] = api_key
            if not ssl_verify:
                ctx = _insecure_ssl_context()
                kwargs["http_options"] = types.HttpOptions(
                    client_args={"verify": ctx},
                    async_client_args={"verify": ctx},
                )
            self._gemini = genai.Client(**kwargs)

    async def complete_json(
        self, *, prompt_key: str, variables: dict[str, Any], thinking_budget: int = 0
    ) -> dict[str, Any]:
        bundle = self._prompts[prompt_key]
        # Auto-fill the skills vocabulary for the extraction prompt from the
        # catalog (names only — codes never reach the LLM). Done here so callers
        # stay unaware of the catalog; absent/empty catalog degrades gracefully.
        variables = self._with_catalog_context(prompt_key, bundle.user_template, variables)
        # Use literal replacement instead of str.format() because the templates
        # embed JSON schemas with real { and } characters that .format() would
        # parse as placeholders and raise KeyError on.
        user = bundle.user_template
        for key, value in variables.items():
            user = user.replace("{" + key + "}", str(value))
        start = time.perf_counter()
        try:
            if (
                self._provider == "gemini"
                and self._cache_enabled
                and prompt_key == _EXTRACTION_PROMPT_KEY
                and _CACHE_SPLIT_MARKER in user
            ):
                result = await self._complete_gemini_cached(
                    system=bundle.system, user=user, thinking_budget=thinking_budget
                )
            elif self._provider == "gemini":
                result = await self._complete_gemini_json(
                    system=bundle.system,
                    user=user.replace(_CACHE_SPLIT_MARKER, "").strip(),
                    thinking_budget=thinking_budget,
                )
            elif self._provider == "openai_compatible":
                result = await self._complete_openai_compatible_json(
                    system=bundle.system, user=user.replace(_CACHE_SPLIT_MARKER, "").strip()
                )
            else:
                raise ValueError(
                    f"Unsupported LLM_PROVIDER={self._provider!r}; use 'gemini' or 'openai_compatible'."
                )
        except Exception:
            llm_errors_total.labels(prompt_key=prompt_key, provider=self._provider).inc()
            raise
        finally:
            llm_duration_seconds.labels(
                prompt_key=prompt_key, provider=self._provider
            ).observe(time.perf_counter() - start)
        return result

    async def _complete_gemini_json(
        self, *, system: str, user: str, thinking_budget: int = 0
    ) -> dict[str, Any]:
        if self._gemini is None:
            raise RuntimeError("Gemini client not initialized")
        config_kwargs: dict[str, Any] = {
            "system_instruction": system,
            "max_output_tokens": 4096,
            "temperature": 0.1,
            "response_mime_type": "application/json",
            "thinking_config": types.ThinkingConfig(thinking_budget=thinking_budget),
        }
        resp = await self._gemini.aio.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        text = getattr(resp, "text", None) or ""
        if not text:
            raise RuntimeError("Gemini returned empty response (check safety / quota).")
        return _parse_json_from_llm(text)

    @staticmethod
    def _with_catalog_context(
        prompt_key: str, template: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        """Inject catalog data into extraction prompt variables.

        Fills ``{skills_catalog}``, ``{establishments_list}`` and
        ``{languages_list}`` from the process-wide catalog store when not
        already supplied by the caller.
        """
        if prompt_key != _EXTRACTION_PROMPT_KEY:
            return variables
        from app.services.catalog_store import catalog_store

        extra: dict[str, Any] = {}
        if "{skills_catalog}" in template and "skills_catalog" not in variables:
            extra["skills_catalog"] = catalog_store.skill_names_block()
        if "{establishments_list}" in template and "establishments_list" not in variables:
            extra["establishments_list"] = catalog_store.establishments_block()
        if "{languages_list}" in template and "languages_list" not in variables:
            extra["languages_list"] = catalog_store.languages_block()
        if not extra:
            return variables
        return {**variables, **extra}

    async def _complete_gemini_cached(
        self, *, system: str, user: str, thinking_budget: int = 0
    ) -> dict[str, Any]:
        """Gemini call using a context-cached stable prefix + per-CV tail.

        Splits the rendered prompt on the marker, (re)creates a cached content
        for the prefix keyed by the catalog fingerprint, and sends only the
        variable tail at generate time. Any cache failure falls back to the
        plain single-shot call so extraction never breaks on a cache problem.
        """
        if self._gemini is None:
            raise RuntimeError("Gemini client not initialized")
        prefix, _, suffix = user.partition(_CACHE_SPLIT_MARKER)
        prefix = prefix.strip()
        suffix = suffix.strip()

        cache_name = await self._get_or_create_cache(system=system, prefix=prefix)
        if cache_name is None:
            # Cache unavailable (too small, API error, …) → uncached fallback.
            return await self._complete_gemini_json(
                system=system, user=f"{prefix}\n\n{suffix}", thinking_budget=thinking_budget
            )

        config = types.GenerateContentConfig(
            cached_content=cache_name,
            max_output_tokens=4096,
            temperature=0.1,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
        )
        try:
            resp = await self._gemini.aio.models.generate_content(
                model=self._model, contents=suffix, config=config
            )
        except Exception:
            # A stale/expired cache handle 404s — drop it and retry uncached.
            self._cache_name = None
            self._cache_fingerprint = None
            return await self._complete_gemini_json(
                system=system, user=f"{prefix}\n\n{suffix}", thinking_budget=thinking_budget
            )
        text = getattr(resp, "text", None) or ""
        if not text:
            raise RuntimeError("Gemini returned empty response (check safety / quota).")
        return _parse_json_from_llm(text)

    async def _get_or_create_cache(self, *, system: str, prefix: str) -> str | None:
        """Return a usable cached-content name, (re)creating it as needed.

        Reuses the in-process handle while the catalog fingerprint is unchanged
        and the TTL has not lapsed. Returns ``None`` (caller falls back to the
        uncached path) on any creation error — e.g. the prefix is below
        Gemini's minimum cacheable token count.
        """
        if self._gemini is None:
            return None
        from app.services.catalog_store import catalog_store

        fingerprint = catalog_store.fingerprint
        now = time.monotonic()
        if (
            self._cache_name is not None
            and self._cache_fingerprint == fingerprint
            and now < self._cache_expires_at
        ):
            return self._cache_name

        try:
            cache = await self._gemini.aio.caches.create(
                model=self._model,
                config=types.CreateCachedContentConfig(
                    system_instruction=system,
                    contents=[prefix],
                    ttl=f"{self._cache_ttl_seconds}s",
                    display_name="cv_entity_extraction_prefix",
                ),
            )
        except Exception:
            self._cache_name = None
            self._cache_fingerprint = None
            return None

        self._cache_name = getattr(cache, "name", None)
        self._cache_fingerprint = fingerprint
        # Refresh a touch before the server TTL to avoid racing expiry.
        self._cache_expires_at = now + max(self._cache_ttl_seconds - 60, 1)
        return self._cache_name

    async def _complete_openai_compatible_json(self, *, system: str, user: str) -> dict[str, Any]:
        """OpenAI-compatible Chat Completions (local vLLM, Ollama OpenAI API, etc.)."""
        import httpx

        if not self._base_url:
            raise ValueError("LLM_BASE_URL is required when LLM_PROVIDER=openai_compatible")
        base = self._base_url.rstrip("/")
        url = f"{base}/chat/completions"
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        async with httpx.AsyncClient(timeout=120.0, verify=self._ssl_verify) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = msg.get("content") or ""
        return _parse_json_from_llm(text)


_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        settings = get_settings()
        _llm_client = LLMClient(
            provider=settings.llm_provider,
            api_key=settings.llm_api_key or "",
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            prompts_dir=Path(__file__).resolve().parents[2] / "prompts",
            ssl_verify=settings.llm_ssl_verify,
            cache_enabled=settings.gemini_cache_enabled,
            cache_ttl_seconds=settings.gemini_cache_ttl_seconds,
        )
    return _llm_client


def reset_llm_client_cache() -> None:
    """Clear cached client (for tests)."""
    global _llm_client
    _llm_client = None
