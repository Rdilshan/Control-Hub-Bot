"""Integration tests for the complete video processing pipeline flow."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
    ClientBotStatus,
    JobStatus,
    JobType,
    ProcessingStatus,
    VideoStatus,
    ViewerStatus,
)
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.sponsor_config import SponsorConfig
from app.db.models.viewer import Viewer
from app.repositories.broadcast import BroadcastRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository
from app.repositories.video_processing import VideoProcessingRepository
from app.schemas.unlockify import UnlockifyLinkData
from app.services.unlockify_client import UnlockifyClient
from app.services.video_creation_service import VideoCreationService
from app.workers.video_processing import VideoProcessingWorker


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
async def test_end_to_end_video_ingest_and_processing_flow(db_session: AsyncSession):
    """End-to-end integration test:

    1. Client Bot created with active sponsor & active viewers
    2. Admin uploads a video via /createvideo intake
    3. Video record (RECEIVED) and background job (PENDING) created
    4. Worker claims and processes the job:
       - Downloads small source thumbnail and uploads reusable Telegram Photo
       - Calls Unlockify API to generate unlock link
       - Persists checkpoints and marks Video READY
       - Creates LIVE Broadcast targeting active viewers and queues BROADCAST job
       - Marks video processing job COMPLETED
    """
    # 1. Setup entities
    client = Client(telegram_user_id=301, username="client301")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=77701,
        username="CinemaBot",
        public_id="bot_cinema301",
        token_encrypted=encrypt_token("999999:BOT_TOKEN_CINEMA"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    sponsor = SponsorConfig(
        client_bot_id=bot.id,
        is_enabled=True,
        sponsor_url="https://sponsor.ink/cinema-deal",
    )
    viewer1 = Viewer(
        client_bot_id=bot.id,
        telegram_user_id=5001,
        username="viewer_one",
        status=ViewerStatus.ACTIVE,
    )
    viewer2 = Viewer(
        client_bot_id=bot.id,
        telegram_user_id=5002,
        username="viewer_two",
        status=ViewerStatus.ACTIVE,
    )
    db_session.add_all([sponsor, viewer1, viewer2])
    await db_session.commit()

    # 2. Intake video via VideoCreationService
    creation_service = VideoCreationService(db_session)
    await creation_service.set_creation_state(bot.id, 301, "WAITING_FOR_VIDEO")

    mock_tg_creation = MagicMock()
    mock_tg_creation.send_message = AsyncMock(return_value={"message_id": 10})

    video_payload = {
        "update_type": "message",
        "telegram_user_id": 301,
        "chat_id": 301,
        "message_id": 101,
        "caption": "🎬 Blockbuster 2026 Premiere",
        "video": {
            "file_id": "tg_vid_cinema_file_001",
            "file_unique_id": "uniq_cinema_001",
            "file_size": 45000000,
            "duration": 180,
            "width": 1920,
            "height": 1080,
            "mime_type": "video/mp4",
            "file_name": "blockbuster.mp4",
            "thumbnail": {"file_id": "tg_thumb_001"},
        },
    }

    intake_res = await creation_service.process_video_intake(
        client_bot=bot,
        telegram_user_id=301,
        chat_id=301,
        admin_id=None,
        actor_data=video_payload,
        telegram_client=mock_tg_creation,
    )
    assert intake_res["ok"] is True
    video_id = intake_res["video_id"]

    # 3. Check video and processing job in database
    video_repo = VideoRepository(db_session)
    video = await video_repo.get_by_id(video_id)
    assert video.status == VideoStatus.RECEIVED

    job_repo = BackgroundJobRepository(db_session)
    jobs = await job_repo.list_by_bot(bot.id)
    assert len(jobs) == 1
    process_job = jobs[0]
    assert process_job.job_type == JobType.VIDEO_PROCESS
    assert process_job.status == JobStatus.PENDING

    # 4. Worker executes the job
    mock_unlockify = MagicMock(spec=UnlockifyClient)
    mock_unlockify.create_link = AsyncMock(
        return_value=UnlockifyLinkData(
            id="link_cinema_888",
            title="🎬 Blockbuster 2026 Premiere",
            ads_count=1,
            unlock_url="https://developer.unlockify.ink/u/link_cinema_888",
        )
    )

    tg_send_photo_res = {
        "message_id": 77,
        "photo": [{"file_id": "reusable_cinema_preview_photo_id", "width": 800, "height": 600}],
    }

    with patch("app.telegram.client.TelegramClient.get_file", new_callable=AsyncMock) as mock_get_file, \
         patch("app.telegram.client.TelegramClient.download_file", new_callable=AsyncMock) as mock_download_file, \
         patch("app.telegram.client.TelegramClient.send_photo", new_callable=AsyncMock) as mock_send_photo, \
         patch("app.telegram.client.TelegramClient.delete_message", new_callable=AsyncMock) as mock_del_msg:

        mock_get_file.return_value = {"file_path": "thumbs/cinema.jpg"}
        mock_download_file.return_value = b"\xff\xd8\xff\xe0cinema_thumb_bytes"
        mock_send_photo.return_value = tg_send_photo_res
        mock_del_msg.return_value = True

        from app.services.video_processing_service import VideoProcessingService
        processing_service = VideoProcessingService(
            session=db_session,
            unlockify_client=mock_unlockify,
        )
        worker = VideoProcessingWorker(
            session=db_session,
            video_processing_service=processing_service,
        )

        job_res = await worker.process_job(process_job.id)
        assert job_res["ok"] is True
        assert job_res["status"] == "READY"

    # 5. Verify post-processing system state
    await db_session.refresh(video)
    assert video.status == VideoStatus.READY
    assert video.published_at is not None

    proc_repo = VideoProcessingRepository(db_session)
    proc = await proc_repo.get_by_video_id(video.id)
    assert proc.status == ProcessingStatus.READY
    assert proc.thumbnail_file_id == "reusable_cinema_preview_photo_id"
    assert proc.unlock_url == "https://developer.unlockify.ink/u/link_cinema_888"

    await db_session.refresh(process_job)
    assert process_job.status == JobStatus.COMPLETED

    # Verify LIVE Broadcast was created targeting the 2 active viewers
    broadcast_repo = BroadcastRepository(db_session)
    broadcast = await broadcast_repo.get_by_video_id(video.id)
    assert broadcast is not None
    assert broadcast.total_targets == 2
    assert broadcast.target_type == "ALL_ACTIVE_VIEWERS"

    # Verify BROADCAST background job was scheduled
    broadcast_jobs, count = await job_repo.list_paginated(job_type=JobType.BROADCAST)
    assert count == 1
    assert broadcast_jobs[0].broadcast_id == broadcast.id
    assert broadcast_jobs[0].status == JobStatus.PENDING
