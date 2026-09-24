"""Unit tests for platform monitoring, queue pressure, job inspection, and system health services."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    BroadcastStatus,
    ClientBotStatus,
    ClientStatus,
    JobStatus,
    JobType,
    VideoStatus,
    ViewerStatus,
)
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.broadcast import Broadcast
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.viewer import Viewer
from app.services.broadcast_monitoring_service import BroadcastMonitoringService
from app.services.job_monitoring_service import JobMonitoringService
from app.services.platform_stats_service import PlatformStatsService
from app.services.queue_monitoring_service import QueueMonitoringService
from app.services.system_monitoring_service import SystemMonitoringService


@pytest.mark.asyncio
async def test_platform_stats_service(db_session: AsyncSession):
    client1 = Client(telegram_user_id=8801, username="client1", status=ClientStatus.ACTIVE)
    client2 = Client(telegram_user_id=8802, username="client2", status=ClientStatus.SUSPENDED)
    db_session.add_all([client1, client2])
    await db_session.flush()

    bot1 = ClientBot(client_id=client1.id, telegram_bot_id=9901, username="Bot1", status=ClientBotStatus.ACTIVE)
    bot2 = ClientBot(client_id=client2.id, telegram_bot_id=9902, username="Bot2", status=ClientBotStatus.PAUSED)
    db_session.add_all([bot1, bot2])
    await db_session.flush()

    service = PlatformStatsService(db_session)
    system_stats = await service.get_system_stats(bypass_cache=True)

    assert system_stats["clients"]["total"] == 2
    assert system_stats["clients"]["active"] == 1
    assert system_stats["clients"]["suspended"] == 1
    assert system_stats["bots"]["total"] == 2
    assert system_stats["bots"]["active"] == 1
    assert system_stats["bots"]["paused"] == 1


@pytest.mark.asyncio
async def test_queue_monitoring_service(db_session: AsyncSession):
    # Add pending video and broadcast jobs
    job1 = BackgroundJob(
        job_type=JobType.VIDEO_PROCESS,
        status=JobStatus.PENDING,
        payload={},
        scheduled_at=utc_now() - timedelta(minutes=3),
    )
    job2 = BackgroundJob(
        job_type=JobType.BROADCAST,
        status=JobStatus.PENDING,
        payload={},
        scheduled_at=utc_now() - timedelta(seconds=45),
    )
    job3 = BackgroundJob(
        job_type=JobType.CATCHUP,
        status=JobStatus.RETRYING,
        payload={},
        scheduled_at=utc_now(),
    )
    db_session.add_all([job1, job2, job3])
    await db_session.commit()

    service = QueueMonitoringService(db_session)
    summary = await service.get_queue_summary()

    assert summary["durable"]["video_processing"] == 1
    assert summary["durable"]["broadcasts"] == 1
    assert summary["durable"]["retrying"] == 1
    assert "3m" in summary["oldest_waiting"]
    assert "Healthy" in summary["status_label"] or "Backlog" in summary["status_label"]


@pytest.mark.asyncio
async def test_job_monitoring_service(db_session: AsyncSession):
    job_failed = BackgroundJob(
        job_type=JobType.VIDEO_PROCESS,
        status=JobStatus.FAILED,
        payload={"video_id": 10},
        attempt_count=3,
        max_attempts=3,
        last_error_code="UNLOCKIFY_TIMEOUT",
        last_error_message="Unlockify upstream gateway timed out after 10s",
    )
    job_stale = BackgroundJob(
        job_type=JobType.BROADCAST,
        status=JobStatus.RUNNING,
        payload={"broadcast_id": 2},
        started_at=utc_now() - timedelta(minutes=30),
    )
    db_session.add_all([job_failed, job_stale])
    await db_session.commit()

    service = JobMonitoringService(db_session)
    detail = await service.get_job_detail(job_failed.id)

    assert detail is not None
    assert detail["is_retryable"] is True
    assert detail["safe_error"]["error_code"] == "UNLOCKIFY_TIMEOUT"
    assert "timed out" in detail["safe_error"]["error_message"]

    # Test stale detection
    stale_jobs = await service.detect_stale_jobs(threshold_seconds=600)
    assert len(stale_jobs) == 1
    assert stale_jobs[0].id == job_stale.id

    # Test retry
    success, msg, retried = await service.retry_job(job_failed.id)
    assert success is True
    assert retried.status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_broadcast_monitoring_service(db_session: AsyncSession):
    bot = ClientBot(client_id=1, telegram_bot_id=7701, username="MovieBot", status=ClientBotStatus.ACTIVE)
    db_session.add(bot)
    await db_session.flush()

    bcast = Broadcast(
        client_bot_id=bot.id,
        video_id=1,
        broadcast_type="LIVE",
        status=BroadcastStatus.RUNNING,
        total_targets=1000,
        sent_count=750,
        blocked_count=50,
        failed_count=0,
    )
    db_session.add(bcast)
    await db_session.commit()

    service = BroadcastMonitoringService(db_session)
    detail = await service.get_broadcast_detail(bcast.id)

    assert detail is not None
    assert detail["total_targets"] == 1000
    assert detail["sent"] == 750
    assert detail["blocked"] == 50
    assert detail["remaining"] == 200
    assert detail["progress_percentage"] == 80.0


@pytest.mark.asyncio
async def test_system_monitoring_service():
    service = SystemMonitoringService()

    # When no workers registered
    with patch("app.services.system_monitoring_service.get_redis") as mock_get_redis:
        mock_redis = AsyncMock()
        mock_redis.smembers.return_value = set()
        mock_get_redis.return_value = mock_redis

        worker_status = await service.get_worker_statuses()
        assert worker_status["total_workers"] == 0
        assert worker_status["online_workers"] == 0
