from __future__ import annotations

import logging

from pythonjsonlogger.json import JsonFormatter


def configure_logging() -> None:
    """Configure structured JSON logging."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter("%(levelname)s %(name)s %(message)s %(cv_id)s %(job_id)s"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]

