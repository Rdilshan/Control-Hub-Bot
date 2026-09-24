"""Integration test covering the end-to-end Client Bot Lifecycle journey:
Active -> Pause -> Resume -> Disconnect -> Reconnect -> Invalid Token Handling.
"""

from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
    BotAdminRole,
    BroadcastStatus,
    ClientBotStatus,
    ClientStatus,
    VideoStatus,
    ViewerStatus,
)
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.broadcast import Broadcast
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.client_bot_settings import ClientBotSettings
from app.db.models.sponsor_config import SponsorConfig
from app.db.models.video import Video
from app.db.models.viewer import Viewer
from app.services.client_bot_health_service import ClientBotHealthService
from app.services.client_bot_lifecycle_service import ClientBotLifecycleService
from app.services.client_bot_reconnect_service import ClientBotReconnectService
from app.services.video_creation_service import VideoCreationService
from app.services.viewer_service import ViewerService
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramInvalidTokenError


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
async def test_full_client_bot_lifecycle_integration_journey(db_session: AsyncSession):
    # 1. Onboard Client and create ACTIVE Client Bot
    client = Client(telegram_user_id=77001, username="cinema_owner", status=ClientStatus.ACTIVE)
    db_session.add(client)
    await db_session.flush()

    raw_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    enc_token = encrypt_token(raw_token)

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=123456789,
        username="cinemabot",
        display_name="Cinema Bot",
        token_encrypted=enc_token,
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    admin = ClientBotAdmin(
        client_bot_id=bot.id,
        telegram_user_id=client.telegram_user_id,
        role=BotAdminRole.OWNER,
    )
    db_session.add(admin)

    settings = ClientBotSettings(
        client_bot_id=bot.id,
        start_message="Welcome to Cinema Bot",
    )
    db_session.add(settings)

    sponsor = SponsorConfig(
        client_bot_id=bot.id,
        is_enabled=True,
        button_text="🔓 Unlock Clip",
    )
    db_session.add(sponsor)

    # Add a Video and a LIVE Broadcast
    video = Video(
        client_bot_id=bot.id,
        status=VideoStatus.READY,
        telegram_file_id="vid_file_101",
        telegram_file_unique_id="uniq_vid_101",
        caption="Action Movie Trailer",
    )
    db_session.add(video)
    await db_session.flush()

    broadcast = Broadcast(
        client_bot_id=bot.id,
        video_id=video.id,
        status=BroadcastStatus.RUNNING,
        total_targets=50,
        sent_count=10,
    )
    db_session.add(broadcast)
    await db_session.commit()

    lifecycle_svc = ClientBotLifecycleService(db_session)
    reconnect_svc = ClientBotReconnectService(db_session)
    health_svc = ClientBotHealthService(db_session)
    viewer_svc = ViewerService(db_session)
    video_creation_svc = VideoCreationService(db_session)

    # =========================================================================
    # PHASE A: PAUSE BOT
    # =========================================================================
    pause_ok, pause_msg, paused_bot = await lifecycle_svc.pause_bot(bot.id, client.id)
    assert pause_ok is True
    assert paused_bot.status == ClientBotStatus.PAUSED
    assert paused_bot.paused_at is not None

    # Verify LIVE broadcast is PAUSED
    await db_session.refresh(broadcast)
    assert broadcast.status == BroadcastStatus.PAUSED

    # Verify Viewer /start receives paused message
    mock_viewer_tg = AsyncMock(spec=TelegramClient)
    start_resp = await viewer_svc.handle_viewer_start(
        client_bot=bot,
        telegram_user_id=99001,
        chat_id=99001,
        telegram_client=mock_viewer_tg,
        username="viewer_bob",
    )
    assert start_resp["action"] == "bot_paused"
    mock_viewer_tg.send_message.assert_called_once()
    assert "paused" in mock_viewer_tg.send_message.call_args.kwargs["text"].lower()

    # Verify /createvideo is blocked while PAUSED
    mock_admin_tg = AsyncMock(spec=TelegramClient)
    create_resp = await video_creation_svc.start_create_video_session(
        client_bot=bot,
        telegram_user_id=client.telegram_user_id,
        chat_id=client.telegram_user_id,
        telegram_client=mock_admin_tg,
    )
    assert create_resp["ok"] is False
    assert create_resp["error"] == "bot_not_active"

    # =========================================================================
    # PHASE B: RESUME BOT
    # =========================================================================
    mock_tg = AsyncMock()
    mock_tg.get_me.return_value = type("BotInfo", (), {"username": "cinemabot", "first_name": "Cinema Bot"})()

    with patch("app.services.client_bot_lifecycle_service.TelegramClient", return_value=mock_tg):
        resume_ok, resume_msg, resumed_bot = await lifecycle_svc.resume_bot(bot.id, client.id)

    assert resume_ok is True
    assert resumed_bot.status == ClientBotStatus.ACTIVE
    assert resumed_bot.paused_at is None

    # Verify LIVE broadcast resumed to QUEUED
    await db_session.refresh(broadcast)
    assert broadcast.status == BroadcastStatus.QUEUED

    # =========================================================================
    # PHASE C: DISCONNECT BOT
    # =========================================================================
    mock_tg_disc = AsyncMock()
    mock_tg_disc.delete_webhook.return_value = True

    with patch("app.services.client_bot_lifecycle_service.TelegramClient", return_value=mock_tg_disc):
        disc_ok, disc_msg = await lifecycle_svc.complete_disconnect(bot.id)

    assert disc_ok is True
    await db_session.refresh(bot)
    assert bot.status == ClientBotStatus.DISCONNECTED
    assert bot.token_encrypted is None
    assert bot.disconnected_at is not None

    # Verify historical data is 100% preserved
    await db_session.refresh(video)
    assert video.status == VideoStatus.READY
    await db_session.refresh(settings)
    assert settings.start_message == "Welcome to Cinema Bot"

    # =========================================================================
    # PHASE D: RECONNECT BOT
    # =========================================================================
    new_token = "123456789:NEWfreshBotFatherToken1234567890"
    mock_tg_reconn = AsyncMock()
    mock_tg_reconn.get_me.return_value = type(
        "BotInfo",
        (),
        {"id": bot.telegram_bot_id, "username": "cinemabot", "first_name": "Cinema Bot"},
    )()
    mock_tg_reconn.set_webhook.return_value = True
    mock_tg_reconn.set_my_commands.return_value = True

    with patch("app.services.client_bot_reconnect_service.TelegramClient", return_value=mock_tg_reconn):
        reconn_ok, reconn_msg, reconnected_bot = await reconnect_svc.reconnect_bot(
            client_bot_id=bot.id,
            client_id=client.id,
            token=new_token,
        )

    assert reconn_ok is True
    assert reconnected_bot.status == ClientBotStatus.ACTIVE
    assert reconnected_bot.token_encrypted is not None
    assert reconnected_bot.disconnected_at is None

    # =========================================================================
    # PHASE E: CONFIRMED UNAUTHORIZED TOKEN IN BotFather
    # =========================================================================
    mock_tg_unauth = AsyncMock()
    mock_tg_unauth.get_me.side_effect = TelegramInvalidTokenError("401 Unauthorized")

    with patch("app.services.client_bot_health_service.TelegramClient", return_value=mock_tg_unauth):
        is_healthy, h_msg, details = await health_svc.check_bot_health(bot.id)

    assert is_healthy is False
    assert details["status"] == ClientBotStatus.INVALID_TOKEN.value
    await db_session.refresh(bot)
    assert bot.status == ClientBotStatus.INVALID_TOKEN
