from __future__ import annotations

import logging

from celery import Celery
from celery.signals import worker_process_init

from app.config import get_settings


def make_celery() -> Celery:
    settings = get_settings()
    app = Celery("cv_intelligence")
    app.conf.broker_url = settings.celery_broker_url
    app.conf.result_backend = settings.redis_url
    app.conf.task_default_queue = "default"
    app.conf.task_routes = {
        "app.tasks.ingestion.ocr_if_needed": {"queue": "ocr"},
    }
    app.conf.include = ["app.tasks.ingestion"]
    return app


celery_app = make_celery()


@worker_process_init.connect
def _prewarm_ocr(**_: object) -> None:
    """Pre-warm the EasyOCR model in each Celery worker process."""
    log = logging.getLogger("cv_layer.startup")
    try:
        from app.services.ocr_service import _get_reader

        log.info("Pre-warming EasyOCR model in worker process…")
        _get_reader()
        log.info("EasyOCR model ready in worker.")
    except Exception as exc:
        log.warning("OCR pre-warm failed in worker (will load on first task): %s", exc)

