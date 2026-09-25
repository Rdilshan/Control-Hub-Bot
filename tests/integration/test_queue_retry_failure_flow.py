"""Integration Test for Queue, Retry, Failure Classification, and Recovery Flow."""

from datetime import timedelta
import pytest
from app.core.enums import (
    BroadcastStatus,
    ClientBotStatus,
    ClientStatus,
    DeliveryStatus,
    ErrorClassification,
    ErrorCode,
    JobStatus,
    JobType,
    ProcessingStatus,
    VideoStatus,
)


from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.broadcast import Broadcast
from app.db.models.broadcast_delivery import BroadcastDelivery
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.db.models.viewer import Viewer
from app.jobs.dispatcher import JobDispatcher
from app.jobs.failure_classifier import JobFailureClassifier
from app.jobs.recovery import JobRecoveryService
from app.repositories.broadcast import BroadcastRepository
from app.repositories.broadcast_delivery import BroadcastDeliveryRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository
from app.repositories.video_processing import VideoProcessingRepository
from app.services.job_retry_service import JobRetryService
from app.services.telegram_rate_limit_coordinator import TelegramRateLimitCoordinator
from app.workers.telegram_updates import process_telegram_update_job
from app.workers.unlockify import process_unlockify_link_job


@pytest.mark.asyncio
async def test_full_queue_retry_failure_recovery_flow(db_session):
    # Setup test entities
    client = Client(telegram_user_id=1001, username="test_client", status=ClientStatus.ACTIVE)
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=123456,
        username="QueueTestBot",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    job_repo = BackgroundJobRepository(db_session)
    rate_limiter = TelegramRateLimitCoordinator()

    # 1. Telegram update deduplication
    update_job = await job_repo.create_job(
        job_type=JobType.TELEGRAM_UPDATE_PROCESS,
        payload={"update_id": 99991},
        client_bot_id=bot.id,
    )
    success1 = await process_telegram_update_job(
        session=db_session,
        job_id=update_job.id,
        client_bot_id=bot.id,
        update_id=99991,
        update_data={"message": {"text": "hello"}},
        rate_limiter=rate_limiter,
    )
    assert success1 is True

    # Duplicate update
    dup_job = await job_repo.create_job(
        job_type=JobType.TELEGRAM_UPDATE_PROCESS,
        payload={"update_id": 99991},
        client_bot_id=bot.id,
    )
    success2 = await process_telegram_update_job(
        session=db_session,
        job_id=dup_job.id,
        client_bot_id=bot.id,
        update_id=99991,
        update_data={"message": {"text": "hello"}},
        rate_limiter=rate_limiter,
    )
    assert success2 is True

    # 2. Video creation and PENDING job
    video = Video(
        client_bot_id=bot.id,
        source_chat_id=-100123,
        telegram_message_id=55,
        telegram_file_id="vid_flow_123",
        telegram_file_unique_id="uniq_flow_123",
        status=VideoStatus.PROCESSING,
    )
    db_session.add(video)
    await db_session.flush()

    proc = VideoProcessing(
        video_id=video.id,
        status=ProcessingStatus.CREATING_UNLOCK_LINK,
        thumbnail_file_id="thumb_flow_abc",
    )
    db_session.add(proc)
    await db_session.flush()


    video_job = await job_repo.create_video_processing_job(
        video_id=video.id,
        client_bot_id=bot.id,
        client_id=client.id,
        thumbnail_file_id="thumb_flow_abc",
    )
    assert video_job.status == JobStatus.PENDING

    # 3. Dispatcher claims and queues job
    dispatcher = JobDispatcher(session=db_session)
    dispatched = await dispatcher.dispatch_due_jobs()
    assert len(dispatched) >= 1
    assert video_job.status == JobStatus.QUEUED

    # 4. Unlockify temporary timeout retry
    class FailingUnlockify:
        async def create_link(self, sponsor_url, video_id):
            raise Exception("ConnectTimeout: Unlockify timed out")

    fail_res = await process_unlockify_link_job(
        session=db_session,
        job_id=video_job.id,
        video_id=video.id,
        client_bot_id=bot.id,
        sponsor_url="https://sponsor.com/ad",
        unlockify_client=FailingUnlockify(),
    )
    assert fail_res is False
    assert video_job.status == JobStatus.RETRYING
    assert video_job.last_error_code == ErrorCode.UNLOCKIFY_TIMEOUT.value

    # 5. Unlockify succeeds on retry -> video READY
    class WorkingUnlockify:
        async def create_link(self, sponsor_url, video_id):
            return f"https://unlockify.it/v/{video_id}"

    success_res = await process_unlockify_link_job(
        session=db_session,
        job_id=video_job.id,
        video_id=video.id,
        client_bot_id=bot.id,
        sponsor_url="https://sponsor.com/ad",
        unlockify_client=WorkingUnlockify(),
    )
    assert success_res is True
    assert video_job.status == JobStatus.COMPLETED
    assert proc.status == ProcessingStatus.READY

    # 6. Telegram 429 rate limit coordination
    exc_429 = Exception("Telegram retry after 4 seconds")
    details_429 = JobFailureClassifier.classify(exc_429)
    assert details_429.classification == ErrorClassification.RATE_LIMITED
    await rate_limiter.set_rate_limit(bot.id, details_429.retry_after or 4)
    assert await rate_limiter.is_rate_limited(bot.id) is True

    # 7. Blocked viewer failure handling
    exc_blocked = Exception("Forbidden: bot was blocked by the user")
    details_blocked = JobFailureClassifier.classify(exc_blocked)
    assert details_blocked.classification == ErrorClassification.BLOCKED_USER
    assert details_blocked.is_retryable is False

    # 8. Worker crash recovery (stale RUNNING job)
    stale_job = await job_repo.create_job(
        job_type=JobType.BROADCAST,
        payload={"broadcast_id": 10},
        client_bot_id=bot.id,
    )
    stale_job.status = JobStatus.RUNNING
    stale_job.started_at = utc_now() - timedelta(seconds=500)
    stale_job.last_heartbeat_at = utc_now() - timedelta(seconds=500)
    stale_job.attempt_count = 1
    await db_session.flush()

    recovery_service = JobRecoveryService(db_session)
    stale_recovered = await recovery_service.recover_stale_running_jobs(threshold_seconds=300)
    assert len(stale_recovered) == 1
    assert stale_recovered[0].status == JobStatus.RETRYING
