from __future__ import annotations

from celery import Celery

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
    app.autodiscover_tasks(["app.tasks"])
    return app


celery_app = make_celery()

