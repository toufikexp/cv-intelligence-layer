from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.config import get_settings


@lru_cache(maxsize=1)
def _load_fasttext(model_path: Path):
    import fasttext  # type: ignore

    return fasttext.load_model(str(model_path))


async def detect_language(text: str) -> str:
    """Detect language (fr/en/mixed) using fasttext if available."""

    settings = get_settings()
    if not text.strip():
        return "mixed"

    try:
        model = _load_fasttext(settings.fasttext_model_path)
        label, prob = model.predict(text.replace("\n", " ")[:2000])
        if not label:
            return "mixed"
        lang = label[0].replace("__label__", "")
        if lang.startswith("fr"):
            return "fr"
        if lang.startswith("en"):
            return "en"
        # Low confidence -> mixed
        if prob and prob[0] < 0.6:
            return "mixed"
        return "mixed"
    except Exception:
        return "mixed"

