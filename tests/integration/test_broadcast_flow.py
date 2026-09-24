"""Integration tests for the complete Live Broadcast Flow."""

from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.broadcast_creation_service import BroadcastCreationService
from app.services.broadcast_service import BroadcastService
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.db.base import Base
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


@pytest.mark.asyncio
async def test_live_broadcast_end_to_end_flow(db_session: AsyncSession):
    """End-to-end integration test for LIVE video preview broadcast."""
    # 1. Setup Client, ClientBot, and Viewers
    client = Client(telegram_user_id=8888, username="media_network_client", status=ClientStatus.ACTIVE)
    db_session.add(client)
    await db_session.flush()

    raw_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    encrypted_token = encrypt_token(raw_token)

    bot = ClientBot(
        client_id=client.id,
        username="media_channel_bot",
        telegram_bot_id=123456789,
        token_encrypted=encrypted_token,
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    # Create 4 active viewers + 1 who will block the bot
    viewers = []
    for i in range(1, 6):
        v = Viewer(
            client_bot_id=bot.id,
            telegram_user_id=2000 + i,
            username=f"viewer_{i}",
            status=ViewerStatus.ACTIVE,
        )
        db_session.add(v)
        viewers.append(v)
    await db_session.flush()

    # 2. Setup READY Video with preview photo and Unlockify URL
    video = Video(
        client_bot_id=bot.id,
        caption="Breaking News Video\n\nMust-watch breaking news update",
        status=VideoStatus.READY,
        telegram_file_id="tg_video_file_id_999",
        telegram_file_unique_id="uniq_vid_999",
    )
    db_session.add(video)
    await db_session.flush()

    video_proc = VideoProcessing(
        video_id=video.id,
        thumbnail_file_id="tg_preview_photo_id_888",
        unlock_url="https://developer.unlockify.ink/u/breakingNews",
        status=ProcessingStatus.READY,
    )
    db_session.add(video_proc)
    await db_session.flush()

    # 3. Create Live Broadcast using BroadcastCreationService
    creation_service = BroadcastCreationService(db_session)
    broadcast = await creation_service.create_live_broadcast(video=video, client_bot=bot)
    await db_session.commit()

    assert broadcast.id is not None
    assert broadcast.total_targets == 5
    assert broadcast.broadcast_type == "LIVE"

    # Verify background job created
    job_repo = BackgroundJobRepository(db_session)
    jobs = await job_repo.get_pending_jobs(job_type=JobType.BROADCAST)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.broadcast_id == broadcast.id

    # 4. Mock Telegram Client behavior
    mock_tg = AsyncMock(spec=TelegramClient)

    async def mock_send_photo(chat_id, photo, caption=None, parse_mode=None, reply_markup=None):
        # Viewer 5 blocks the bot
        if chat_id == 2005:
            raise TelegramForbiddenError("Forbidden: bot was blocked by the user")
        return {"message_id": int(chat_id) * 10}

    mock_tg.send_photo.side_effect = mock_send_photo

    # 5. Process the broadcast job via LiveBroadcastWorker and BroadcastService
    broadcast_service = BroadcastService(db_session)
    worker = LiveBroadcastWorker(db_session, broadcast_service=broadcast_service)

    # Inject mock telegram client in broadcast service execution
    with patch("app.services.broadcast_service.TelegramClient", return_value=mock_tg):
        result = await broadcast_service.run_broadcast(
            broadcast_id=broadcast.id,
            telegram_client=mock_tg,
            batch_size=2,
        )

    assert result["ok"] is True
    assert result["status"] == BroadcastStatus.COMPLETED
    assert result["sent_count"] == 4
    assert result["blocked_count"] == 1
    assert result["failed_count"] == 0

    # 6. Verify Telegram calls: ONLY send_photo was called, NEVER send_video!
    assert mock_tg.send_photo.call_count == 5
    mock_tg.send_video.assert_not_called()

    # Verify inline keyboard passed to send_photo has unlock_url
    first_call_kwargs = mock_tg.send_photo.call_args_list[0][1]
    assert first_call_kwargs["photo"] == "tg_preview_photo_id_888"
    assert "Breaking News Video" in first_call_kwargs["caption"]
    assert first_call_kwargs["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://developer.unlockify.ink/u/breakingNews"

    # 7. Verify Delivery Records in DB
    delivery_repo = BroadcastDeliveryRepository(db_session)
    deliveries_map = await delivery_repo.get_deliveries_for_viewers(
        broadcast_id=broadcast.id,
        viewer_ids=[v.id for v in viewers],
    )
    assert len(deliveries_map) == 5
    assert deliveries_map[viewers[0].id].status == DeliveryStatus.SENT
    assert deliveries_map[viewers[4].id].status == DeliveryStatus.BLOCKED

    # 8. Verify Broadcast final state in DB
    broadcast_repo = BroadcastRepository(db_session)
    final_b = await broadcast_repo.get_by_id(broadcast.id)
    assert final_b.status == BroadcastStatus.COMPLETED
    assert final_b.sent_count == 4
    assert final_b.blocked_count == 1
    assert final_b.total_targets == 5
    assert final_b.completed_at is not None
    assert final_b.progress_percentage == 100.0
