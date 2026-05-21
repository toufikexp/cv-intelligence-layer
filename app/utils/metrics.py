"""Prometheus metric definitions for the CV Intelligence Layer.

All metrics are module-level singletons on the default ``prometheus_client``
registry so that ``prometheus-fastapi-instrumentator`` and these custom metrics
share the same ``/metrics`` output. This module imports only from
``prometheus_client`` to avoid import cycles.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# --- CV pipeline ---
cv_processed_total = Counter(
    "cvlayer_cv_processed_total",
    "CVs that finished or failed the pipeline",
    ["status"],  # success | failed
)
cv_unprocessable_total = Counter(
    "cvlayer_cv_unprocessable_total",
    "CVs rejected as unreadable",
)
cv_ocr_fallback_total = Counter(
    "cvlayer_cv_ocr_fallback_total",
    "CVs where OCR fallback was triggered",
)
ocr_duration_seconds = Histogram(
    "cvlayer_ocr_duration_seconds",
    "OCR processing wall time in seconds",
    buckets=(1, 2, 5, 10, 20, 30, 60, 120),
)
entity_extraction_duration_seconds = Histogram(
    "cvlayer_entity_extraction_duration_seconds",
    "Full entity extraction time in seconds",
    buckets=(1, 2, 5, 10, 20, 30, 60),
)

# --- LLM ---
llm_duration_seconds = Histogram(
    "cvlayer_llm_duration_seconds",
    "LLM call latency in seconds",
    ["prompt_key", "provider"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
)
llm_errors_total = Counter(
    "cvlayer_llm_errors_total",
    "LLM call failures",
    ["prompt_key", "provider"],
)
