"""Integration test for full Sponsor Configuration + Unlock Link + Video Delivery Flow."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
    ClientBotStatus,
    DeliveryStatus,
    ProcessingStatus,
    VideoStatus,
    ViewerStatus,
)
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.repositories.video import VideoRepository
from app.repositories.video_delivery import VideoDeliveryRepository
from app.repositories.viewer import ViewerRepository
from app.schemas.unlockify import UnlockifyLinkData
from app.services.client_bot_sponsor_service import ClientBotSponsorService
from app.services.unlockify_client import UnlockifyClient
from app.services.video_processing_service import VideoProcessingService
from app.telegram.client import TelegramClient
from app.telegram.client_bot.context import ClientBotActorContext, ClientBotContext
from app.telegram.client_bot.viewer_router import ClientViewerRouter


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
async def test_full_sponsor_unlock_and_delivery_lifecycle(db_session: AsyncSession):
    """Full lifecycle test:

    1. Client Admin configures sponsor URL
    2. Video is processed and receives Unlockify link with canonical Telegram deep link destination
    3. Video marks READY
    4. Viewer sends /start unlock_<video_public_id> update to Client Bot
    5. ClientViewerRouter routes to ViewerUnlockService
    6. Same Client Bot delivers the actual video by saved telegram_file_id without VPS downloads
    7. Delivery history and Viewer record are updated
    """
    # 1. Setup client and bot
    client = Client(telegram_user_id=8001, username="cinema_client")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=99988,
        username="BlockbusterCinemaBot",
        public_id="bot_blockbuster",
        token_encrypted=encrypt_token("99988:BOT_TOKEN_BB"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    # 2. Configure sponsor via ClientBotSponsorService
    sponsor_service = ClientBotSponsorService(db_session)
    sponsor = await sponsor_service.set_sponsor_url(bot.id, "https://sponsor.ink/cinema-deal-1")
    assert sponsor.is_enabled is True
    await db_session.commit()

    # 3. Create video and run processing pipeline
    video_repo = VideoRepository(db_session)
    video = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="tg_vid_master_asset_007",
        telegram_file_unique_id="uniq_asset_007",
        file_name="sci_fi_thriller_2026.mp4",
        caption="🌌 Sci-Fi Thriller 2026",
        duration_seconds=300,
        source_chat_id=8001,
    )
    await db_session.commit()

    # Mock Unlockify client
    mock_unlockify = MagicMock(spec=UnlockifyClient)
    mock_unlockify.create_link = AsyncMock(
        return_value=UnlockifyLinkData(
            id="unl_scifi_99",
            title="🌌 Sci-Fi Thriller 2026",
            ads_count=1,
            unlock_url="https://developer.unlockify.ink/u/unl_scifi_99",
        )
    )

    # Process video
    with patch("app.telegram.client.TelegramClient.send_photo", new_callable=AsyncMock) as mock_send_photo, \
         patch("app.telegram.client.TelegramClient.delete_message", new_callable=AsyncMock) as mock_del_msg:

        mock_send_photo.return_value = {
            "message_id": 12,
            "photo": [{"file_id": "scifi_preview_photo_id", "width": 800, "height": 600}],
        }
        mock_del_msg.return_value = True

        processing_service = VideoProcessingService(session=db_session, unlockify_client=mock_unlockify)
        proc_res = await processing_service.process_video(video.id)
        assert proc_res["ok"] is True
        assert proc_res["status"] == "READY"

        # Verify Unlockify request was made with the Telegram deep link destination
        mock_unlockify.create_link.assert_called_once_with(
            title="🌌 Sci-Fi Thriller 2026",
            advertisement_urls=["https://sponsor.ink/cinema-deal-1"],
            destination_url="https://t.me/BlockbusterCinemaBot?start=unlock_" + video.public_id,
        )

    await db_session.refresh(video)
    assert video.status == VideoStatus.READY

    # 4. Viewer triggers /start unlock_<video.public_id>
    mock_tg_viewer = MagicMock(spec=TelegramClient)
    mock_tg_viewer.send_video = AsyncMock(return_value={"message_id": 5501})

    viewer_router = ClientViewerRouter(telegram_client=mock_tg_viewer)

    bot_ctx = ClientBotContext(
        client_bot_id=bot.id,
        client_id=client.id,
        telegram_bot_id=bot.telegram_bot_id,
        bot_username=bot.username,
        display_name=bot.display_name,
        status=bot.status,
        public_bot_id=bot.public_id,
    )
    actor_ctx = ClientBotActorContext(
        telegram_user_id=1234567,
        chat_id=1234567,
        chat_type="private",
        role="VIEWER",
        username="space_fan",
        first_name="Space",
        last_name="Fan",
        language_code="en",
    )
    actor_data = {
        "update_type": "message",
        "text": f"/start unlock_{video.public_id}",
        "telegram_user_id": 1234567,
        "chat_id": 1234567,
        "username": "space_fan",
        "first_name": "Space",
    }

    with patch("app.telegram.client.TelegramClient.send_video", new_callable=AsyncMock) as mock_send_vid:
        mock_send_vid.return_value = {"message_id": 5501}

        route_res = await viewer_router.handle(
            bot_ctx=bot_ctx,
            actor=actor_ctx,
            actor_data=actor_data,
            session=db_session,
        )

        assert route_res["ok"] is True
        assert route_res["status"] == "SENT"
        assert route_res["message_id"] == 5501

        # Verify video was delivered via sendVideo with saved telegram_file_id
        mock_send_vid.assert_called_once()
        call_kwargs = mock_send_vid.call_args.kwargs
        assert call_kwargs["chat_id"] == 1234567
        assert call_kwargs["video"] == "tg_vid_master_asset_007"
        assert "Sci-Fi Thriller" in call_kwargs["caption"]

    # 5. Verify database records
    delivery_repo = VideoDeliveryRepository(db_session)
    count = await delivery_repo.count_by_video(video.id, status=DeliveryStatus.SENT)
    assert count == 1

    viewer_repo = ViewerRepository(db_session)
    viewer = await viewer_repo.get_by_bot_and_telegram_user(bot.id, 1234567)
    assert viewer is not None
    assert viewer.status == ViewerStatus.ACTIVE
    assert viewer.username == "space_fan"
