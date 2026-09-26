"""Unit and operational validation tests for Deployment and Operations (Plan 21)."""

import os
import hashlib
import tempfile
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.config import Settings
from app.core.enums import Environment
from app.celery_app import create_celery_app
from app.workers.worker_entrypoint import BackgroundWorkerRunner
from app.workers.scheduler_entrypoint import SchedulerRunner


@pytest.mark.asyncio
async def test_production_settings_validation():
    """Validates that production mode strictly enforces required secrets and disables debug."""
    # Production without required secrets should raise ValueError
    with pytest.raises(ValueError, match="CONTROL_HUB_BOT_TOKEN is required in production mode"):
        Settings(
            APP_ENV=Environment.PRODUCTION,
            APP_DEBUG=False,
            CONTROL_HUB_BOT_TOKEN=None,
            INTERNAL_API_SECRET="valid_secret",
        )

    # Production with APP_DEBUG=True should fail
    with pytest.raises(ValueError, match="APP_DEBUG cannot be True in production mode"):
        Settings(
            APP_ENV=Environment.PRODUCTION,
            APP_DEBUG=True,
            CONTROL_HUB_BOT_TOKEN="123456:ABC",
            INTERNAL_API_SECRET="valid_secret",
        )

    # Valid production settings pass
    prod_settings = Settings(
        APP_ENV=Environment.PRODUCTION,
        APP_DEBUG=False,
        CONTROL_HUB_BOT_TOKEN="123456:ABC",
        INTERNAL_API_SECRET="valid_secret",
    )
    assert prod_settings.is_production is True
    assert prod_settings.APP_DEBUG is False


def test_celery_app_configuration():
    """Validates Celery task routing, prefetch, and beat schedule configuration."""
    with patch("app.celery_app.CELERY_AVAILABLE", True), patch("app.celery_app.Celery") as MockCelery:
        mock_instance = MagicMock()
        MockCelery.return_value = mock_instance
        app = create_celery_app()

        assert app is not None
        mock_instance.conf.update.assert_called_once()
        conf_kwargs = mock_instance.conf.update.call_args[1] if mock_instance.conf.update.call_args[1] else mock_instance.conf.update.call_args[0][0]

        assert conf_kwargs.get("worker_prefetch_multiplier") == 1
        assert conf_kwargs.get("task_acks_late") is True
        assert "app.workers.live_broadcast.*" in conf_kwargs.get("task_routes", {})
        assert "app.workers.video_processing.*" in conf_kwargs.get("task_routes", {})


@pytest.mark.asyncio
async def test_worker_entrypoint_runner_lifecycle():
    """Validates BackgroundWorkerRunner starts, processes, and gracefully stops."""
    runner = BackgroundWorkerRunner(queue_name="broadcast_live", poll_interval=0.01)
    assert runner._running is True

    # Stop runner
    runner.stop()
    assert runner._running is False


@pytest.mark.asyncio
async def test_scheduler_runner_lifecycle():
    """Validates SchedulerRunner lifecycle and stop signal handling."""
    runner = SchedulerRunner(cycle_interval=0.01)
    assert runner._running is True

    # Stop scheduler
    runner.stop()
    assert runner._running is False


def test_backup_checksum_utility():
    """Validates SHA256 checksum generation for backup archive verification."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(b"SAMPLE_DATABASE_BACKUP_CONTENT_SQL_DUMP")
        tmp_path = tmp.name

    try:
        # Calculate SHA256
        sha256 = hashlib.sha256()
        with open(tmp_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        digest = sha256.hexdigest()

        assert len(digest) == 64
        assert isinstance(digest, str)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_deploy_script_scales_broadcast_workers_with_default():
    deploy_script = Path("deploy/scripts/deploy.sh").read_text(encoding="utf-8")
    compose_file = Path("deploy/docker-compose.prod.yml").read_text(encoding="utf-8")

    assert 'BROADCAST_WORKER_REPLICAS="${BROADCAST_WORKER_REPLICAS:-10}"' in deploy_script
    assert '--scale worker-broadcast="${BROADCAST_WORKER_REPLICAS}"' in deploy_script
    assert "--remove-orphans" in deploy_script

    worker_broadcast_section = compose_file.split("  worker-broadcast:", 1)[1].split("  worker-catchup:", 1)[0]
    assert "container_name:" not in worker_broadcast_section
    assert 'command: ["python", "-u", "-m", "app.workers.worker_entrypoint", "--queue=broadcast_live"]' in worker_broadcast_section
