from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings
from app.services.prompt_loader import PromptBundle, load_prompt


def _parse_json_from_llm(text: str) -> dict[str, Any]:
    """Parse JSON from model output; strip optional markdown fences."""
    t = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL | re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    return json.loads(t)


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
    ) -> None:
        self._provider = provider.lower().strip()
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._prompts: dict[str, PromptBundle] = {
            "cv_entity_extraction": load_prompt(prompts_dir / "cv_entity_extraction.md"),
            "cv_ranking": load_prompt(prompts_dir / "cv_ranking.md"),
            "answer_scoring": load_prompt(prompts_dir / "answer_scoring.md"),
        }
        self._gemini: genai.Client | None = None
        if self._provider == "gemini":
            self._gemini = genai.Client(api_key=api_key) if api_key else genai.Client()

    async def complete_json(
        self, *, prompt_key: str, variables: dict[str, Any], thinking_budget: int = 0
    ) -> dict[str, Any]:
        bundle = self._prompts[prompt_key]
        # Use literal replacement instead of str.format() because the templates
        # embed JSON schemas with real { and } characters that .format() would
        # parse as placeholders and raise KeyError on.
        user = bundle.user_template
        for key, value in variables.items():
            user = user.replace("{" + key + "}", str(value))
        start = time.perf_counter()
        if self._provider == "gemini":
            result = await self._complete_gemini_json(
                system=bundle.system, user=user, thinking_budget=thinking_budget
            )
        elif self._provider == "openai_compatible":
            result = await self._complete_openai_compatible_json(system=bundle.system, user=user)
        else:
            raise ValueError(
                f"Unsupported LLM_PROVIDER={self._provider!r}; use 'gemini' or 'openai_compatible'."
            )
        _ = time.perf_counter() - start
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
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = msg.get("content") or ""
        return _parse_json_from_llm(text)


def get_llm_client() -> LLMClient:
    settings = get_settings()
    return LLMClient(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        prompts_dir=Path(__file__).resolve().parents[2] / "prompts",
    )
