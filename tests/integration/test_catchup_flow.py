"""Integration tests for the complete New User Catch-Up Flow."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
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
from app.repositories.viewer_catchup import ViewerCatchupRepository
from app.services.broadcast_creation_service import BroadcastCreationService
from app.services.broadcast_service import BroadcastService
from app.services.catchup_service import CatchupService
from app.services.viewer_service import ViewerService
from app.telegram.client import TelegramClient
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


@pytest.mark.asyncio
async def test_end_to_end_catchup_flow_with_live_coordination(db_session: AsyncSession):
    """End-to-end integration test for New User Catch-Up:

    1. Client Bot has 3 pre-existing READY videos
    2. New Viewer joins via /start
    3. ViewerCatchup state initialized and background job queued
    4. Worker executes catch-up delivering historical video previews
    5. Admin uploads Video #4 which triggers LIVE broadcast
    6. Viewer receives Video #4 via LIVE broadcast
    7. Catch-up does not duplicate Video #4
    8. Catch-up completes cleanly
    """
    # 1. Setup Client and ClientBot
    client = Client(telegram_user_id=9901, username="catchup_owner", status=ClientStatus.ACTIVE)
    db_session.add(client)
    await db_session.flush()

    raw_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    encrypted_token = encrypt_token(raw_token)

    bot = ClientBot(
        client_id=client.id,
        username="movie_bot",
        telegram_bot_id=123456789,
        token_encrypted=encrypted_token,
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    # 2. Add 3 Historical READY videos
    videos = []
    for i in range(1, 4):
        v = Video(
            client_bot_id=bot.id,
            caption=f"Movie Trailer #{i}",
            status=VideoStatus.READY,
            telegram_file_id=f"file_id_{i}",
            telegram_file_unique_id=f"uniq_{i}",
        )
        db_session.add(v)
        await db_session.flush()

        vp = VideoProcessing(
            video_id=v.id,
            thumbnail_file_id=f"thumb_{i}",
            unlock_url=f"https://developer.unlockify.ink/u/movie_{i}",
            status=ProcessingStatus.READY,
        )
        db_session.add(vp)
        videos.append(v)
    await db_session.commit()

    # 3. Viewer joins via ViewerService.handle_viewer_start
    mock_tg = AsyncMock(spec=TelegramClient)
    mock_tg.send_photo.return_value = {"message_id": 5001}
    mock_tg.send_message.return_value = {"message_id": 5000}

    viewer_service = ViewerService(db_session)
    start_res = await viewer_service.handle_viewer_start(
        client_bot=bot,
        telegram_user_id=112233,
        chat_id=112233,
        telegram_client=mock_tg,
        username="new_viewer_bob",
    )
    assert start_res["ok"] is True
    assert start_res["is_new"] is True
    viewer_id = start_res["viewer_id"]

    # 4. Verify ViewerCatchup state and BackgroundJob
    catchup_repo = ViewerCatchupRepository(db_session)
    catchup = await catchup_repo.get_by_viewer_id(viewer_id)
    assert catchup is not None
    assert catchup.status == CatchupStatus.PENDING
    assert catchup.target_max_video_id == videos[-1].id
    assert catchup.total_eligible == 3

    job_repo = BackgroundJobRepository(db_session)
    jobs = await job_repo.get_pending_jobs(job_type=JobType.CATCHUP)
    assert len(jobs) == 1
    job = jobs[0]

    # 5. Worker processes catchup
    catchup_worker = CatchupWorker(db_session)
    with patch("app.services.catchup_delivery_service.TelegramClient", return_value=mock_tg):
        worker_res = await catchup_worker.process_job(job.id)

    assert worker_res["ok"] is True
    assert worker_res["delivered_count"] == 3
    assert worker_res["is_completed"] is True

    # Check that 3 preview photos were dispatched
    assert mock_tg.send_photo.call_count == 3
    mock_tg.send_video.assert_not_called()

    # 6. Admin creates Video #4 and runs LIVE broadcast
    v4 = Video(
        client_bot_id=bot.id,
        caption="Movie Trailer #4 (LIVE)",
        status=VideoStatus.READY,
        telegram_file_id="file_id_4",
        telegram_file_unique_id="uniq_4",
    )
    db_session.add(v4)
    await db_session.flush()

    vp4 = VideoProcessing(
        video_id=v4.id,
        thumbnail_file_id="thumb_4",
        unlock_url="https://developer.unlockify.ink/u/movie_4",
        status=ProcessingStatus.READY,
    )
    db_session.add(vp4)
    await db_session.flush()

    broadcast_creation = BroadcastCreationService(db_session)
    broadcast = await broadcast_creation.create_live_broadcast(video=v4, client_bot=bot)
    await db_session.commit()

    # Run LIVE broadcast for video 4
    broadcast_service = BroadcastService(db_session)
    with patch("app.services.broadcast_service.TelegramClient", return_value=mock_tg):
        b_res = await broadcast_service.run_broadcast(
            broadcast_id=broadcast.id,
            telegram_client=mock_tg,
        )
    assert b_res["ok"] is True
    assert b_res["sent_count"] == 1

    # 7. Check cross-source duplicate protection: Video #4 must not be sent again via Catch-up
    delivery_repo = CatchupDeliveryRepository(db_session)
    has_received_v4 = await delivery_repo.has_received_video(viewer_id=viewer_id, video_id=v4.id)
    assert has_received_v4 is True  # Received via LIVE!

    # 8. Check final catch-up state
    final_catchup = await catchup_repo.get_by_viewer_id(viewer_id)
    assert final_catchup.status == CatchupStatus.COMPLETED
    assert final_catchup.delivered_count == 3
