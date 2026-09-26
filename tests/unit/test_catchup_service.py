"""Unit tests for CatchupVideoSelectorService, CatchupDeliveryService, CatchupSchedulerService, CatchupService, and CatchupWorker."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
    BroadcastStatus,
    CatchupStatus,
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
from app.db.models.catchup_delivery import CatchupDelivery
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.db.models.viewer import Viewer
from app.db.models.viewer_catchup import ViewerCatchup
from app.repositories.catchup import CatchupDeliveryRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.viewer import ViewerRepository
from app.repositories.viewer_catchup import ViewerCatchupRepository
from app.services.catchup_delivery_service import CatchupDeliveryService
from app.services.catchup_scheduler_service import CatchupSchedulerService
from app.services.catchup_service import CatchupService
from app.services.catchup_video_selector_service import CatchupVideoSelectorService
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramForbiddenError, TelegramRateLimitError
from app.workers.catchup_worker import CatchupWorker


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
async def catchup_setup(db_session: AsyncSession):
    client = Client(telegram_user_id=55501, username="test_catchup_client", status=ClientStatus.ACTIVE)
    db_session.add(client)
    await db_session.flush()

    token_str = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    encrypted_token = encrypt_token(token_str)

    bot = ClientBot(
        client_id=client.id,
        username="catchup_bot",
        telegram_bot_id=123456789,
        token_encrypted=encrypted_token,
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    # Create 5 historical READY videos
    videos = []
    for i in range(1, 6):
        v = Video(
            client_bot_id=bot.id,
            caption=f"Historical Video #{i}",
            status=VideoStatus.READY,
            telegram_file_id=f"tg_vid_file_{i}",
            telegram_file_unique_id=f"uniq_vid_{i}",
        )
        db_session.add(v)
        await db_session.flush()

        vp = VideoProcessing(
            video_id=v.id,
            thumbnail_file_id=f"tg_thumb_{i}",
            unlock_url=f"https://developer.unlockify.ink/u/clip_{i}",
            status=ProcessingStatus.READY,
        )
        db_session.add(vp)
        videos.append(v)
    await db_session.flush()

    # Create a new viewer
    viewer = Viewer(
        client_bot_id=bot.id,
        telegram_user_id=77701,
        username="new_viewer_alice",
        status=ViewerStatus.ACTIVE,
    )
    db_session.add(viewer)
    await db_session.commit()

    return {
        "client": client,
        "bot": bot,
        "videos": videos,
        "viewer": viewer,
        "raw_token": token_str,
    }


# ============================================================================
# 1. CatchupVideoSelectorService Tests
# ============================================================================

@pytest.mark.asyncio
async def test_video_selector_unseen_videos(db_session: AsyncSession, catchup_setup):
    bot = catchup_setup["bot"]
    viewer = catchup_setup["viewer"]
    selector = CatchupVideoSelectorService(db_session)

    max_id = await selector.get_max_ready_video_id(bot.id)
    assert max_id == catchup_setup["videos"][-1].id

    count = await selector.count_eligible_unseen_videos(bot.id, viewer.id, target_max_video_id=max_id)
    assert count == 5

    # Fetch first batch of 2
    batch1 = await selector.get_next_eligible_videos(
        client_bot_id=bot.id,
        viewer_id=viewer.id,
        cursor_video_id=0,
        target_max_video_id=max_id,
        limit=2,
    )
    assert len(batch1) == 2
    assert batch1[0].id == catchup_setup["videos"][0].id
    assert batch1[1].id == catchup_setup["videos"][1].id


@pytest.mark.asyncio
async def test_video_selector_skips_already_delivered(db_session: AsyncSession, catchup_setup):
    bot = catchup_setup["bot"]
    viewer = catchup_setup["viewer"]
    videos = catchup_setup["videos"]
    selector = CatchupVideoSelectorService(db_session)
    catchup_delivery_repo = CatchupDeliveryRepository(db_session)

    # Simulate Video #1 already delivered via Catchup
    await catchup_delivery_repo.record_delivery(
        client_bot_id=bot.id,
        viewer_id=viewer.id,
        video_id=videos[0].id,
        status=CatchupStatus.SENT,
    )
    await db_session.commit()

    eligible = await selector.get_next_eligible_videos(
        client_bot_id=bot.id,
        viewer_id=viewer.id,
        cursor_video_id=0,
        limit=10,
    )
    assert len(eligible) == 4
    assert videos[0].id not in [v.id for v in eligible]


# ============================================================================
# 2. CatchupDeliveryService Tests
# ============================================================================

@pytest.mark.asyncio
async def test_catchup_delivery_success(db_session: AsyncSession, catchup_setup):
    bot = catchup_setup["bot"]
    viewer = catchup_setup["viewer"]
    video = catchup_setup["videos"][0]

    delivery_service = CatchupDeliveryService(db_session)
    mock_tg = AsyncMock(spec=TelegramClient)
    mock_tg.send_photo.return_value = {"message_id": 887766}

    status, msg_id, err_code, err_msg = await delivery_service.send_catchup_preview_to_viewer(
        client_bot=bot,
        viewer=viewer,
        video=video,
        telegram_client=mock_tg,
    )

    assert status == CatchupStatus.SENT
    assert msg_id == 887766
    assert err_code is None

    # Check delivery record in DB
    cd_repo = CatchupDeliveryRepository(db_session)
    rec = await cd_repo.get_by_viewer_and_video(viewer.id, video.id)
    assert rec is not None
    assert rec.status == CatchupStatus.SENT
    assert rec.telegram_message_id == 887766


@pytest.mark.asyncio
async def test_catchup_delivery_blocked_handling(db_session: AsyncSession, catchup_setup):
    bot = catchup_setup["bot"]
    viewer = catchup_setup["viewer"]
    video = catchup_setup["videos"][0]

    delivery_service = CatchupDeliveryService(db_session)
    mock_tg = AsyncMock(spec=TelegramClient)
    mock_tg.send_photo.side_effect = TelegramForbiddenError("Forbidden: bot was blocked by the user")

    status, msg_id, err_code, err_msg = await delivery_service.send_catchup_preview_to_viewer(
        client_bot=bot,
        viewer=viewer,
        video=video,
        telegram_client=mock_tg,
    )

    assert status == CatchupStatus.BLOCKED
    assert err_code == "TELEGRAM_FORBIDDEN"

    viewer_repo = ViewerRepository(db_session)
    updated_viewer = await viewer_repo.get_by_bot_and_telegram_user(bot.id, viewer.telegram_user_id)
    assert updated_viewer.status == ViewerStatus.BLOCKED


# ============================================================================
# 3. CatchupSchedulerService Tests
# ============================================================================

@pytest.mark.asyncio
async def test_scheduler_live_priority_yield(db_session: AsyncSession, catchup_setup):
    bot = catchup_setup["bot"]
    video = catchup_setup["videos"][0]
    viewer = catchup_setup["viewer"]
    scheduler = CatchupSchedulerService(db_session)

    # Initial state: no live broadcast
    assert await scheduler.has_live_broadcast_in_progress(bot.id) is False
    assert await scheduler.is_bot_available_for_catchup(bot.id) is True

    # Queue a LIVE broadcast for this bot
    b = Broadcast(
        client_bot_id=bot.id,
        video_id=video.id,
        broadcast_type="LIVE",
        status=BroadcastStatus.QUEUED,
        total_targets=1,
    )
    db_session.add(b)
    await db_session.commit()

    # Now scheduler must detect LIVE priority and declare bot unavailable for catchup
    assert await scheduler.has_live_broadcast_in_progress(bot.id) is True
    assert await scheduler.is_bot_available_for_catchup(bot.id) is False


# ============================================================================
# 4. CatchupService Lifecycle & Batch Tests
# ============================================================================

@pytest.mark.asyncio
async def test_catchup_service_init_and_batch_processing(db_session: AsyncSession, catchup_setup):
    bot = catchup_setup["bot"]
    viewer = catchup_setup["viewer"]
    service = CatchupService(db_session)

    # 1. Initialize catch-up for new viewer
    catchup, job = await service.initialize_or_resume_catchup(
        client_bot_id=bot.id,
        viewer_id=viewer.id,
    )
    assert catchup is not None
    assert catchup.status == CatchupStatus.PENDING
    assert catchup.total_eligible == 5
    assert job is not None

    # 2. Process batch 1 with batch_size=2
    mock_tg = AsyncMock(spec=TelegramClient)
    mock_tg.send_photo.return_value = {"message_id": 101}

    res1 = await service.process_viewer_catchup_batch(
        viewer_id=viewer.id,
        telegram_client=mock_tg,
        batch_size=2,
    )
    assert res1["ok"] is True
    assert res1["delivered_count"] == 2
    assert res1["remaining_count"] == 3
    assert res1["is_completed"] is False

    # 3. Process remaining batch of 3
    res2 = await service.process_viewer_catchup_batch(
        viewer_id=viewer.id,
        telegram_client=mock_tg,
        batch_size=5,
    )
    assert res2["ok"] is True
    assert res2["delivered_count"] == 3
    assert res2["remaining_count"] == 0
    assert res2["is_completed"] is True

    # 4. Verify DB state
    c_repo = ViewerCatchupRepository(db_session)
    final_catchup = await c_repo.get_by_viewer_id(viewer.id)
    assert final_catchup.status == CatchupStatus.COMPLETED
    assert final_catchup.delivered_count == 5
    assert final_catchup.completed_at is not None


@pytest.mark.asyncio
async def test_catchup_service_zero_historical_videos(db_session: AsyncSession):
    # Setup bot with 0 videos
    client = Client(telegram_user_id=66601, username="empty_bot_owner", status=ClientStatus.ACTIVE)
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        username="empty_vid_bot",
        telegram_bot_id=999888,
        token_encrypted=encrypt_token("tok_123"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    viewer = Viewer(
        client_bot_id=bot.id,
        telegram_user_id=88801,
        username="empty_viewer",
        status=ViewerStatus.ACTIVE,
    )
    db_session.add(viewer)
    await db_session.commit()

    service = CatchupService(db_session)
    catchup, job = await service.initialize_or_resume_catchup(
        client_bot_id=bot.id,
        viewer_id=viewer.id,
    )
    assert catchup.status == CatchupStatus.COMPLETED
    assert job is None


# ============================================================================
# 5. CatchupWorker Tests
# ============================================================================

@pytest.mark.asyncio
async def test_catchup_worker_job_execution(db_session: AsyncSession, catchup_setup):
    bot = catchup_setup["bot"]
    viewer = catchup_setup["viewer"]

    job_repo = BackgroundJobRepository(db_session)
    job = await job_repo.create_job(
        job_type=JobType.CATCHUP,
        client_bot_id=bot.id,
        payload={"viewer_id": viewer.id, "client_bot_id": bot.id},
        queue_name="catchup",
    )
    await db_session.commit()

    mock_service = AsyncMock(spec=CatchupService)
    mock_service.process_viewer_catchup_batch.return_value = {"ok": True, "delivered_count": 2}

    worker = CatchupWorker(db_session, catchup_service=mock_service)
    pending = await worker.get_pending_jobs()
    assert len(pending) >= 1

    res = await worker.process_job(job.id)
    assert res["ok"] is True
    mock_service.process_viewer_catchup_batch.assert_called_once_with(viewer.id)

    updated_job = await job_repo.get_by_id(job.id)
    assert updated_job.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_catchup_worker_schedules_next_batch_for_next_day(db_session: AsyncSession, catchup_setup, monkeypatch):
    bot = catchup_setup["bot"]
    viewer = catchup_setup["viewer"]

    db_session.add(
        ViewerCatchup(
            client_bot_id=bot.id,
            viewer_id=viewer.id,
            status=CatchupStatus.RUNNING,
            target_max_video_id=catchup_setup["videos"][-1].id,
            total_eligible=5,
            delivered_count=2,
            last_video_id=catchup_setup["videos"][1].id,
        )
    )
    await db_session.flush()

    job_repo = BackgroundJobRepository(db_session)
    job = await job_repo.create_job(
        job_type=JobType.CATCHUP,
        client_bot_id=bot.id,
        payload={"viewer_id": viewer.id, "client_bot_id": bot.id},
        queue_name="catchup",
    )
    await db_session.commit()

    settings = MagicMock()
    settings.CATCHUP_BATCH_DELAY_SECONDS = 86_400.0
    monkeypatch.setattr("app.workers.catchup_worker.get_settings", lambda: settings)

    mock_service = AsyncMock(spec=CatchupService)
    mock_service.process_viewer_catchup_batch.return_value = {
        "ok": True,
        "delivered_count": 2,
        "remaining_count": 3,
        "is_completed": False,
    }

    worker = CatchupWorker(db_session, catchup_service=mock_service)
    res = await worker.process_job(job.id)

    assert res["ok"] is True

    jobs = await job_repo.get_pending_jobs(job_type=JobType.CATCHUP, limit=10)
    future_jobs = [j for j in jobs if j.id != job.id]
    assert len(future_jobs) == 0

    all_jobs_stmt = select(BackgroundJob).where(
        BackgroundJob.job_type == JobType.CATCHUP,
        BackgroundJob.id != job.id,
    )
    all_jobs_res = await db_session.execute(all_jobs_stmt)
    next_job = all_jobs_res.scalar_one()
    assert next_job.available_at > next_job.scheduled_at
    assert (next_job.available_at - next_job.scheduled_at).total_seconds() >= 86_399

    catchup_repo = ViewerCatchupRepository(db_session)
    catchup = await catchup_repo.get_by_viewer_id(viewer.id)
    assert catchup.status == CatchupStatus.PAUSED
    assert catchup.paused_reason == "BATCH_DELAY"
