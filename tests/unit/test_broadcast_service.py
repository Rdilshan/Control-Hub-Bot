"""Unit tests for BroadcastAudienceService, TelegramBroadcastRateLimiter, BroadcastDeliveryService, BroadcastScheduler, BroadcastService, and Workers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
    BroadcastStatus,
    ClientBotStatus,
    ClientStatus,
    DeliveryStatus,
    JobStatus,
    JobType,
    ProcessingStatus,
    VideoStatus,
    ViewerStatus,
)
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.background_job import BackgroundJob
from app.db.models.broadcast import Broadcast
from app.db.models.broadcast_delivery import BroadcastDelivery
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.db.models.viewer import Viewer
from app.repositories.broadcast import BroadcastRepository
from app.repositories.delivery import BroadcastDeliveryRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.viewer import ViewerRepository
from app.services.broadcast_audience_service import BroadcastAudienceService
from app.services.broadcast_delivery_service import BroadcastDeliveryService
from app.services.broadcast_scheduler import BroadcastScheduler
from app.services.broadcast_service import BroadcastService
from app.services.telegram_broadcast_rate_limiter import TelegramBroadcastRateLimiter
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramForbiddenError, TelegramRateLimitError
from app.workers.broadcast_retry import BroadcastRetryWorker
from app.workers.live_broadcast import LiveBroadcastWorker


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def sample_setup(db_session: AsyncSession):
    client = Client(telegram_user_id=12345, username="test_client", status=ClientStatus.ACTIVE)
    db_session.add(client)
    await db_session.flush()

    token_str = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    encrypted_token = encrypt_token(token_str)

    bot = ClientBot(
        client_id=client.id,
        username="test_client_bot",
        telegram_bot_id=123456789,
        token_encrypted=encrypted_token,
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    video = Video(
        client_bot_id=bot.id,
        caption="Check out this awesome clip",
        status=VideoStatus.READY,
        telegram_file_id="tg_video_file_id_123",
        telegram_file_unique_id="uniq_vid_123",
    )
    db_session.add(video)
    await db_session.flush()

    video_proc = VideoProcessing(
        video_id=video.id,
        thumbnail_file_id="tg_photo_preview_file_id_456",
        unlock_url="https://developer.unlockify.ink/u/abc12345",
        status=ProcessingStatus.READY,
    )
    db_session.add(video_proc)
    await db_session.flush()

    viewers = []
    for i in range(1, 6):
        v = Viewer(
            client_bot_id=bot.id,
            telegram_user_id=1000 + i,
            username=f"user_{i}",
            status=ViewerStatus.ACTIVE,
        )
        db_session.add(v)
        viewers.append(v)
    await db_session.flush()

    broadcast = Broadcast(
        client_bot_id=bot.id,
        video_id=video.id,
        target_type="ALL_ACTIVE_VIEWERS",
        broadcast_type="LIVE",
        status=BroadcastStatus.QUEUED,
        total_targets=5,
    )
    db_session.add(broadcast)
    await db_session.commit()

    return {
        "client": client,
        "bot": bot,
        "video": video,
        "video_proc": video_proc,
        "viewers": viewers,
        "broadcast": broadcast,
        "raw_token": token_str,
    }


# ============================================================================
# 1. BroadcastAudienceService Tests
# ============================================================================

@pytest.mark.asyncio
async def test_audience_snapshot_and_keyset_pagination(db_session: AsyncSession, sample_setup):
    bot = sample_setup["bot"]
    audience_service = BroadcastAudienceService(db_session)

    total, max_id = await audience_service.capture_audience_snapshot(bot.id)
    assert total == 5
    assert max_id > 0

    # Page 1: limit 2
    page1 = await audience_service.get_next_viewer_page(
        client_bot_id=bot.id,
        cursor_id=0,
        max_id=max_id,
        limit=2,
    )
    assert len(page1) == 2
    assert page1[0].id < page1[1].id

    # Page 2: cursor from page1
    page2 = await audience_service.get_next_viewer_page(
        client_bot_id=bot.id,
        cursor_id=page1[1].id,
        max_id=max_id,
        limit=2,
    )
    assert len(page2) == 2
    assert page2[0].id > page1[1].id

    # Page 3: last viewer
    page3 = await audience_service.get_next_viewer_page(
        client_bot_id=bot.id,
        cursor_id=page2[1].id,
        max_id=max_id,
        limit=2,
    )
    assert len(page3) == 1

    # End of audience
    page4 = await audience_service.get_next_viewer_page(
        client_bot_id=bot.id,
        cursor_id=page3[0].id,
        max_id=max_id,
        limit=2,
    )
    assert len(page4) == 0


@pytest.mark.asyncio
async def test_audience_snapshot_excludes_new_viewers(db_session: AsyncSession, sample_setup):
    bot = sample_setup["bot"]
    audience_service = BroadcastAudienceService(db_session)

    total, max_id = await audience_service.capture_audience_snapshot(bot.id)
    assert total == 5

    # New viewer joins mid-broadcast
    new_viewer = Viewer(
        client_bot_id=bot.id,
        telegram_user_id=9999,
        username="new_joiner",
        status=ViewerStatus.ACTIVE,
    )
    db_session.add(new_viewer)
    await db_session.commit()

    # Query with max_id boundary
    all_in_snapshot = await audience_service.get_next_viewer_page(
        client_bot_id=bot.id,
        cursor_id=0,
        max_id=max_id,
        limit=10,
    )
    assert len(all_in_snapshot) == 5
    assert all(v.id <= max_id for v in all_in_snapshot)


@pytest.mark.asyncio
async def test_audience_empty_bot(db_session: AsyncSession):
    audience_service = BroadcastAudienceService(db_session)
    total, max_id = await audience_service.capture_audience_snapshot(client_bot_id=999)
    assert total == 0
    assert max_id == 0


# ============================================================================
# 2. TelegramBroadcastRateLimiter Tests
# ============================================================================

@pytest.mark.asyncio
async def test_rate_limiter_throttling():
    limiter = TelegramBroadcastRateLimiter(default_rate_per_second=100.0)
    # Should acquire without raising
    await limiter.acquire(client_bot_id=1)
    await limiter.acquire(client_bot_id=1)


@pytest.mark.asyncio
async def test_rate_limiter_429_pause():
    limiter = TelegramBroadcastRateLimiter(default_rate_per_second=100.0)
    assert not limiter.is_bot_paused(client_bot_id=1)

    limiter.pause_bot(client_bot_id=1, retry_after=0.1)
    assert limiter.is_bot_paused(client_bot_id=1)

    await asyncio.sleep(0.15)
    assert not limiter.is_bot_paused(client_bot_id=1)


# ============================================================================
# 3. BroadcastDeliveryService Tests
# ============================================================================

@pytest.mark.asyncio
async def test_delivery_preflight_checks(db_session: AsyncSession, sample_setup):
    delivery_service = BroadcastDeliveryService(db_session)
    broadcast = sample_setup["broadcast"]
    video = sample_setup["video"]
    bot = sample_setup["bot"]
    video_proc = sample_setup["video_proc"]

    # Valid preflight
    is_valid, err = delivery_service.preflight_broadcast(broadcast, video, bot, video_processing=video_proc)
    assert is_valid is True
    assert err is None

    # Invalid video status
    video.status = VideoStatus.PROCESSING
    is_valid, err = delivery_service.preflight_broadcast(broadcast, video, bot, video_processing=video_proc)
    assert is_valid is False
    assert "not READY" in err
    video.status = VideoStatus.READY

    # Missing preview photo
    orig_thumb = video_proc.thumbnail_file_id
    video_proc.thumbnail_file_id = None
    is_valid, err = delivery_service.preflight_broadcast(broadcast, video, bot, video_processing=video_proc)
    assert is_valid is False
    assert "preview_photo_file_id" in err
    video_proc.thumbnail_file_id = orig_thumb

    # Missing unlock url
    orig_url = video_proc.unlock_url
    video_proc.unlock_url = None
    is_valid, err = delivery_service.preflight_broadcast(broadcast, video, bot, video_processing=video_proc)
    assert is_valid is False
    assert "unlock_url" in err
    video_proc.unlock_url = orig_url

    # Inactive bot
    bot.status = ClientBotStatus.PAUSED
    is_valid, err = delivery_service.preflight_broadcast(broadcast, video, bot, video_processing=video_proc)
    assert is_valid is False
    assert "not ACTIVE" in err


@pytest.mark.asyncio
async def test_send_preview_to_viewer_success(db_session: AsyncSession, sample_setup):
    delivery_service = BroadcastDeliveryService(db_session)
    bot = sample_setup["bot"]
    viewer = sample_setup["viewers"][0]
    broadcast = sample_setup["broadcast"]

    mock_tg = AsyncMock(spec=TelegramClient)
    mock_tg.send_photo.return_value = {"message_id": 998877}

    status, msg_id, err_code, err_msg = await delivery_service.send_preview_to_viewer(
        client_bot_id=bot.id,
        bot_token="test_token",
        viewer=viewer,
        broadcast_id=broadcast.id,
        preview_photo_file_id="photo_123",
        unlock_url="https://unlockify.ink/u/abc",
        caption="<b>Test Video</b>",
        telegram_client=mock_tg,
    )

    assert status == DeliveryStatus.SENT
    assert msg_id == 998877
    assert err_code is None

    # Verify delivery record saved
    deliv_repo = BroadcastDeliveryRepository(db_session)
    deliv = await deliv_repo.get_by_broadcast_and_viewer(broadcast.id, viewer.id)
    assert deliv is not None
    assert deliv.status == DeliveryStatus.SENT
    assert deliv.telegram_message_id == 998877


@pytest.mark.asyncio
async def test_send_preview_blocked_user_handling(db_session: AsyncSession, sample_setup):
    delivery_service = BroadcastDeliveryService(db_session)
    bot = sample_setup["bot"]
    viewer = sample_setup["viewers"][0]
    broadcast = sample_setup["broadcast"]

    mock_tg = AsyncMock(spec=TelegramClient)
    mock_tg.send_photo.side_effect = TelegramForbiddenError("Forbidden: bot was blocked by the user")

    status, msg_id, err_code, err_msg = await delivery_service.send_preview_to_viewer(
        client_bot_id=bot.id,
        bot_token="test_token",
        viewer=viewer,
        broadcast_id=broadcast.id,
        preview_photo_file_id="photo_123",
        unlock_url="https://unlockify.ink/u/abc",
        telegram_client=mock_tg,
    )

    assert status == DeliveryStatus.BLOCKED
    assert err_code == "TELEGRAM_FORBIDDEN"

    # Verify viewer is marked BLOCKED
    viewer_repo = ViewerRepository(db_session)
    updated_viewer = await viewer_repo.get_by_bot_and_telegram_user(bot.id, viewer.telegram_user_id)
    assert updated_viewer.status == ViewerStatus.BLOCKED


# ============================================================================
# 4. BroadcastScheduler Tests
# ============================================================================

@pytest.mark.asyncio
async def test_scheduler_one_active_live_per_bot(db_session: AsyncSession, sample_setup):
    scheduler = BroadcastScheduler(db_session)
    broadcast = sample_setup["broadcast"]
    bot = sample_setup["bot"]
    video = sample_setup["video"]

    # Initial queued broadcast is selected
    runnable = await scheduler.get_next_runnable_broadcast()
    assert runnable is not None
    assert runnable.id == broadcast.id

    # Mark this broadcast RUNNING
    broadcast.status = BroadcastStatus.RUNNING
    await db_session.commit()

    # Queue a second broadcast for the same bot
    b2 = Broadcast(
        client_bot_id=bot.id,
        video_id=video.id,
        broadcast_type="LIVE",
        status=BroadcastStatus.QUEUED,
        total_targets=5,
    )
    db_session.add(b2)
    await db_session.commit()

    # Scheduler must NOT pick b2 because bot already has an active LIVE broadcast
    runnable2 = await scheduler.get_next_runnable_broadcast()
    assert runnable2 is None

    # Once broadcast 1 finishes, b2 becomes runnable
    broadcast.status = BroadcastStatus.COMPLETED
    await db_session.commit()

    runnable3 = await scheduler.get_next_runnable_broadcast()
    assert runnable3 is not None
    assert runnable3.id == b2.id


# ============================================================================
# 5. BroadcastService Execution & Recovery Tests
# ============================================================================

@pytest.mark.asyncio
async def test_broadcast_service_full_execution(db_session: AsyncSession, sample_setup):
    service = BroadcastService(db_session)
    broadcast = sample_setup["broadcast"]

    mock_tg = AsyncMock(spec=TelegramClient)
    mock_tg.send_photo.return_value = {"message_id": 12345}

    result = await service.run_broadcast(
        broadcast_id=broadcast.id,
        telegram_client=mock_tg,
        batch_size=2,
    )

    assert result["ok"] is True
    assert result["status"] == BroadcastStatus.COMPLETED
    assert result["sent_count"] == 5
    assert result["failed_count"] == 0
    assert result["blocked_count"] == 0
    assert mock_tg.send_photo.call_count == 5

    # Check DB state
    b_repo = BroadcastRepository(db_session)
    updated = await b_repo.get_by_id(broadcast.id)
    assert updated.status == BroadcastStatus.COMPLETED
    assert updated.sent_count == 5
    assert updated.started_at is not None
    assert updated.completed_at is not None
    assert updated.remaining_count == 0
    assert updated.progress_percentage == 100.0


@pytest.mark.asyncio
async def test_broadcast_service_zero_audience(db_session: AsyncSession, sample_setup):
    bot = sample_setup["bot"]
    video = sample_setup["video"]

    # Deactivate all viewers
    for v in sample_setup["viewers"]:
        v.status = ViewerStatus.INACTIVE
    await db_session.commit()

    b_empty = Broadcast(
        client_bot_id=bot.id,
        video_id=video.id,
        broadcast_type="LIVE",
        status=BroadcastStatus.QUEUED,
        total_targets=0,
    )
    db_session.add(b_empty)
    await db_session.commit()

    service = BroadcastService(db_session)
    result = await service.run_broadcast(broadcast_id=b_empty.id)

    assert result["ok"] is True
    assert result["status"] == BroadcastStatus.COMPLETED
    assert result["total_targets"] == 0


@pytest.mark.asyncio
async def test_broadcast_service_crash_recovery(db_session: AsyncSession, sample_setup):
    broadcast = sample_setup["broadcast"]
    viewers = sample_setup["viewers"]
    delivery_repo = BroadcastDeliveryRepository(db_session)

    # Simulate 2 viewers already sent before worker restart
    await delivery_repo.record_delivery(
        broadcast_id=broadcast.id,
        viewer_id=viewers[0].id,
        status=DeliveryStatus.SENT,
        telegram_message_id=111,
    )
    await delivery_repo.record_delivery(
        broadcast_id=broadcast.id,
        viewer_id=viewers[1].id,
        status=DeliveryStatus.SENT,
        telegram_message_id=222,
    )

    broadcast.sent_count = 2
    broadcast.last_processed_viewer_id = viewers[1].id
    broadcast.audience_max_viewer_id = viewers[-1].id
    broadcast.total_targets = 5
    broadcast.status = BroadcastStatus.RUNNING
    await db_session.commit()

    mock_tg = AsyncMock(spec=TelegramClient)
    mock_tg.send_photo.return_value = {"message_id": 333}

    service = BroadcastService(db_session)
    result = await service.run_broadcast(
        broadcast_id=broadcast.id,
        telegram_client=mock_tg,
    )

    assert result["ok"] is True
    assert result["sent_count"] == 5
    # Only remaining 3 viewers should have been dispatched to Telegram
    assert mock_tg.send_photo.call_count == 3


# ============================================================================
# 6. Worker Tests
# ============================================================================

@pytest.mark.asyncio
async def test_live_broadcast_worker(db_session: AsyncSession, sample_setup):
    broadcast = sample_setup["broadcast"]
    bot = sample_setup["bot"]

    job_repo = BackgroundJobRepository(db_session)
    job = await job_repo.create_broadcast_job(
        broadcast_id=broadcast.id,
        video_id=sample_setup["video"].id,
        client_bot_id=bot.id,
        client_id=sample_setup["client"].id,
    )
    await db_session.commit()

    mock_service = AsyncMock(spec=BroadcastService)
    mock_service.run_broadcast.return_value = {"ok": True, "sent_count": 5}

    worker = LiveBroadcastWorker(db_session, broadcast_service=mock_service)
    pending = await worker.get_pending_jobs()
    assert len(pending) >= 1

    result = await worker.process_job(job.id)
    assert result["ok"] is True
    mock_service.run_broadcast.assert_called_once_with(broadcast.id)

    updated_job = await job_repo.get_by_id(job.id)
    assert updated_job.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_broadcast_retry_worker(db_session: AsyncSession, sample_setup):
    broadcast = sample_setup["broadcast"]
    mock_service = AsyncMock(spec=BroadcastService)
    mock_service.retry_failed_deliveries.return_value = {
        "ok": True,
        "recovered_count": 2,
    }

    worker = BroadcastRetryWorker(db_session, broadcast_service=mock_service)
    result = await worker.process_retry(broadcast.id)
    assert result["ok"] is True
    assert result["recovered_count"] == 2
