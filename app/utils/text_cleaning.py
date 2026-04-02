from __future__ import annotations

import re
import unicodedata


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/tabs into one and multiple newlines into two."""
    t = re.sub(r"[ \t]+", " ", text)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def strip_control_chars(text: str) -> str:
    """Remove non-printable characters except newlines and tabs."""
    return "".join(ch for ch in text if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C"))


def normalize_unicode(text: str) -> str:
    """Apply NFKC unicode normalization."""
    return unicodedata.normalize("NFKC", text)


def clean_text(text: str) -> str:
    """Apply all text cleaning steps."""
    text = normalize_unicode(text)
    text = strip_control_chars(text)
    text = normalize_whitespace(text)
    return text
