"""Celery Application and Distributed Worker Configuration."""

import os
from typing import Any, Dict
from app.config import get_settings

settings = get_settings()

try:
    from celery import Celery
    CELERY_AVAILABLE = True
except ImportError:
    Celery = None  # type: ignore
    CELERY_AVAILABLE = False


def create_celery_app() -> Any:
    """Factory creating configured Celery application instance."""
    broker_url = os.getenv("CELERY_BROKER_URL") or settings.REDIS_URL
    backend_url = os.getenv("CELERY_RESULT_BACKEND") or broker_url

    if not CELERY_AVAILABLE:
        return None

    app = Celery(
        "control_hub",
        broker=broker_url,
        backend=backend_url,
    )

    # Celery Configuration
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_reject_on_worker_lost=True,
        broker_connection_retry_on_startup=True,
        task_routes={
            "app.workers.telegram_updates.*": {"queue": "telegram_updates"},
            "app.workers.video_processing.*": {"queue": "video_processing"},
            "app.workers.unlockify.*": {"queue": "video_processing"},
            "app.workers.live_broadcast.*": {"queue": "broadcast_live"},
            "app.workers.broadcast_retry.*": {"queue": "broadcast_live"},
            "app.workers.catchup_worker.*": {"queue": "catchup"},
            "app.workers.delivery_retry.*": {"queue": "catchup"},
            "app.workers.lifecycle.*": {"queue": "lifecycle"},
            "app.workers.lifecycle_worker.*": {"queue": "lifecycle"},
            "app.workers.maintenance.*": {"queue": "lifecycle"},
        },
        task_annotations={
            "app.workers.telegram_updates.*": {"time_limit": 60, "soft_time_limit": 50},
            "app.workers.video_processing.*": {"time_limit": 300, "soft_time_limit": 270},
            "app.workers.live_broadcast.*": {"time_limit": 600, "soft_time_limit": 540},
            "app.workers.catchup_worker.*": {"time_limit": 300, "soft_time_limit": 270},
            "app.workers.lifecycle.*": {"time_limit": 120, "soft_time_limit": 100},
        },
        beat_schedule={
            "recover-stale-jobs-every-minute": {
                "task": "app.workers.maintenance.run_maintenance_recovery_cycle",
                "schedule": 60.0,
            },
            "lifecycle-reconciliation-every-5-minutes": {
                "task": "app.workers.lifecycle.process_lifecycle_reconciliation",
                "schedule": 300.0,
            },
        },
    )

    return app


celery_app = create_celery_app()
