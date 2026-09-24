"""Unit tests for Client Bot Lifecycle Service, Capability Service, Reconnect, and Health."""

from datetime import datetime
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
    BotAdminRole,
    BotEventType,
    BroadcastStatus,
    CatchupStatus,
    ClientBotStatus,
    ClientStatus,
    JobStatus,
    JobType,
    VideoStatus,
)
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.background_job import BackgroundJob
from app.db.models.bot_event import BotEvent
from app.db.models.broadcast import Broadcast
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.client_bot_settings import ClientBotSettings
from app.db.models.video import Video
from app.db.models.viewer_catchup import ViewerCatchup
from app.repositories.client_bot import ClientBotRepository
from app.services.client_bot_health_service import ClientBotHealthService
from app.services.client_bot_lifecycle_service import ClientBotLifecycleService
from app.services.client_bot_reconnect_service import ClientBotReconnectService
from app.services.lifecycle_capability_service import LifecycleCapabilityService
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramInvalidTokenError, TelegramNetworkError
from app.workers.lifecycle_worker import LifecycleWorker


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
async def lifecycle_setup(db_session: AsyncSession):
    client = Client(telegram_user_id=88001, username="test_client_owner", status=ClientStatus.ACTIVE)
    db_session.add(client)
    await db_session.flush()

    raw_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    enc_token = encrypt_token(raw_token)

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=123456789,
        username="lifecycle_bot",
        display_name="Lifecycle Bot",
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
        start_message="Welcome to Lifecycle Bot",
    )
    db_session.add(settings)

    await db_session.commit()
    return {
        "client": client,
        "bot": bot,
        "raw_token": raw_token,
    }


# ============================================================================
# 1. Capability Service Matrix Tests
# ============================================================================

def test_lifecycle_capability_matrix():
    # ACTIVE
    assert LifecycleCapabilityService.can_admin_read(ClientBotStatus.ACTIVE) is True
    assert LifecycleCapabilityService.can_admin_write(ClientBotStatus.ACTIVE) is True
    assert LifecycleCapabilityService.can_viewer_start(ClientBotStatus.ACTIVE) is True
    assert LifecycleCapabilityService.can_create_video(ClientBotStatus.ACTIVE) is True
    assert LifecycleCapabilityService.can_process_video(ClientBotStatus.ACTIVE, requires_telegram=True) is True
    assert LifecycleCapabilityService.can_broadcast(ClientBotStatus.ACTIVE) is True
    assert LifecycleCapabilityService.can_catchup(ClientBotStatus.ACTIVE) is True
    assert LifecycleCapabilityService.can_unlock_delivery(ClientBotStatus.ACTIVE) is True

    # PAUSED
    assert LifecycleCapabilityService.can_admin_read(ClientBotStatus.PAUSED) is True
    assert LifecycleCapabilityService.can_admin_write(ClientBotStatus.PAUSED) is False
    assert LifecycleCapabilityService.can_viewer_start(ClientBotStatus.PAUSED) is False
    assert LifecycleCapabilityService.can_create_video(ClientBotStatus.PAUSED) is False
    assert LifecycleCapabilityService.can_process_video(ClientBotStatus.PAUSED, requires_telegram=True) is False
    assert LifecycleCapabilityService.can_process_video(ClientBotStatus.PAUSED, requires_telegram=False) is True
    assert LifecycleCapabilityService.can_broadcast(ClientBotStatus.PAUSED) is False
    assert LifecycleCapabilityService.can_catchup(ClientBotStatus.PAUSED) is False
    assert LifecycleCapabilityService.can_unlock_delivery(ClientBotStatus.PAUSED) is False
    assert LifecycleCapabilityService.is_paused(ClientBotStatus.PAUSED) is True

    # DISCONNECTED
    assert LifecycleCapabilityService.can_admin_read(ClientBotStatus.DISCONNECTED) is False
    assert LifecycleCapabilityService.can_admin_write(ClientBotStatus.DISCONNECTED) is False
    assert LifecycleCapabilityService.can_viewer_start(ClientBotStatus.DISCONNECTED) is False
    assert LifecycleCapabilityService.is_disconnected(ClientBotStatus.DISCONNECTED) is True


# ============================================================================
# 2. Pause & Resume Flow Tests
# ============================================================================

@pytest.mark.asyncio
async def test_pause_bot_flow(db_session: AsyncSession, lifecycle_setup):
    bot = lifecycle_setup["bot"]
    client = lifecycle_setup["client"]
    service = ClientBotLifecycleService(db_session)

    # Add a running live broadcast
    v = Video(
        client_bot_id=bot.id,
        status=VideoStatus.READY,
        telegram_file_id="vid_file_1",
        telegram_file_unique_id="uniq_vid_1",
    )
    db_session.add(v)
    await db_session.flush()

    bc = Broadcast(client_bot_id=bot.id, video_id=v.id, status=BroadcastStatus.RUNNING, total_targets=10)
    db_session.add(bc)
    await db_session.commit()

    # Pause bot
    success, msg, paused_bot = await service.pause_bot(bot.id, client.id)
    assert success is True
    assert paused_bot.status == ClientBotStatus.PAUSED
    assert paused_bot.paused_at is not None
    assert paused_bot.lifecycle_version == 2

    # Check broadcast status transitioned to PAUSED
    await db_session.refresh(bc)
    assert bc.status == BroadcastStatus.PAUSED

    # Duplicate pause is idempotent
    success_dup, _, _ = await service.pause_bot(bot.id, client.id)
    assert success_dup is True


@pytest.mark.asyncio
async def test_resume_bot_flow(db_session: AsyncSession, lifecycle_setup):
    bot = lifecycle_setup["bot"]
    client = lifecycle_setup["client"]
    service = ClientBotLifecycleService(db_session)

    # Pause first
    await service.pause_bot(bot.id, client.id)

    # Mock Telegram getMe for resume check
    mock_tg = AsyncMock()
    mock_tg.get_me.return_value = type("BotInfo", (), {"username": "lifecycle_bot", "first_name": "Lifecycle Bot"})()

    with patch("app.services.client_bot_lifecycle_service.TelegramClient", return_value=mock_tg):
        success, msg, resumed_bot = await service.resume_bot(bot.id, client.id)

    assert success is True
    assert resumed_bot.status == ClientBotStatus.ACTIVE
    assert resumed_bot.paused_at is None
    assert resumed_bot.lifecycle_version == 3

    # Duplicate resume is idempotent
    success_dup, _, _ = await service.resume_bot(bot.id, client.id)
    assert success_dup is True


@pytest.mark.asyncio
async def test_resume_with_invalid_token_marks_invalid(db_session: AsyncSession, lifecycle_setup):
    bot = lifecycle_setup["bot"]
    client = lifecycle_setup["client"]
    service = ClientBotLifecycleService(db_session)

    # Pause first
    await service.pause_bot(bot.id, client.id)

    # Mock Telegram getMe throwing TelegramInvalidTokenError
    mock_tg = AsyncMock()
    mock_tg.get_me.side_effect = TelegramInvalidTokenError("Unauthorized token")

    with patch("app.services.client_bot_lifecycle_service.TelegramClient", return_value=mock_tg):
        success, msg, _ = await service.resume_bot(bot.id, client.id)

    assert success is False
    await db_session.refresh(bot)
    assert bot.status == ClientBotStatus.INVALID_TOKEN


# ============================================================================
# 3. Disconnect Flow Tests
# ============================================================================

@pytest.mark.asyncio
async def test_disconnect_bot_flow(db_session: AsyncSession, lifecycle_setup):
    bot = lifecycle_setup["bot"]
    client = lifecycle_setup["client"]
    service = ClientBotLifecycleService(db_session)

    # Begin disconnect
    success_init, msg_init, _ = await service.begin_disconnect(bot.id, client.id)
    assert success_init is True
    await db_session.refresh(bot)
    assert bot.status == ClientBotStatus.DISCONNECTING

    # Complete disconnect
    mock_tg = AsyncMock()
    mock_tg.delete_webhook.return_value = True

    with patch("app.services.client_bot_lifecycle_service.TelegramClient", return_value=mock_tg):
        success_comp, msg_comp = await service.complete_disconnect(bot.id)

    assert success_comp is True
    await db_session.refresh(bot)
    assert bot.status == ClientBotStatus.DISCONNECTED
    assert bot.token_encrypted is None
    assert bot.disconnected_at is not None


# ============================================================================
# 4. Reconnect Flow Tests
# ============================================================================

@pytest.mark.asyncio
async def test_reconnect_bot_success(db_session: AsyncSession, lifecycle_setup):
    bot = lifecycle_setup["bot"]
    client = lifecycle_setup["client"]
    lifecycle_service = ClientBotLifecycleService(db_session)
    reconnect_service = ClientBotReconnectService(db_session)

    # Disconnect first
    mock_tg_disc = AsyncMock()
    mock_tg_disc.delete_webhook.return_value = True
    with patch("app.services.client_bot_lifecycle_service.TelegramClient", return_value=mock_tg_disc):
        await lifecycle_service.complete_disconnect(bot.id)

    await db_session.refresh(bot)
    assert bot.status == ClientBotStatus.DISCONNECTED

    # Reconnect with valid token for the SAME telegram_bot_id
    new_token = "123456789:NEWabcdefghijklmnopqrstuvwxyz12345"
    mock_tg = AsyncMock()
    mock_tg.get_me.return_value = type(
        "BotInfo",
        (),
        {"id": bot.telegram_bot_id, "username": "lifecycle_bot", "first_name": "Lifecycle Bot"},
    )()
    mock_tg.set_webhook.return_value = True
    mock_tg.set_my_commands.return_value = True

    with patch("app.services.client_bot_reconnect_service.TelegramClient", return_value=mock_tg):
        success, msg, reconnected_bot = await reconnect_service.reconnect_bot(
            client_bot_id=bot.id,
            client_id=client.id,
            token=new_token,
        )

    assert success is True
    assert reconnected_bot.status == ClientBotStatus.ACTIVE
    assert reconnected_bot.token_encrypted is not None
    assert reconnected_bot.disconnected_at is None


@pytest.mark.asyncio
async def test_reconnect_bot_identity_mismatch_rejected(db_session: AsyncSession, lifecycle_setup):
    bot = lifecycle_setup["bot"]
    client = lifecycle_setup["client"]
    lifecycle_service = ClientBotLifecycleService(db_session)
    reconnect_service = ClientBotReconnectService(db_session)

    # Disconnect
    mock_tg_disc = AsyncMock()
    mock_tg_disc.delete_webhook.return_value = True
    with patch("app.services.client_bot_lifecycle_service.TelegramClient", return_value=mock_tg_disc):
        await lifecycle_service.complete_disconnect(bot.id)

    # Provide token belonging to a DIFFERENT telegram_bot_id (e.g. 999999999 instead of 123456789)
    other_token = "999999999:NEWabcdefghijklmnopqrstuvwxyz12345"
    mock_tg = AsyncMock()
    mock_tg.get_me.return_value = type(
        "BotInfo",
        (),
        {"id": 999999999, "username": "different_bot", "first_name": "Different Bot"},
    )()

    with patch("app.services.client_bot_reconnect_service.TelegramClient", return_value=mock_tg):
        success, msg, reconnected_bot = await reconnect_service.reconnect_bot(
            client_bot_id=bot.id,
            client_id=client.id,
            token=other_token,
        )

    assert success is False
    assert "different_bot" in msg
    await db_session.refresh(bot)
    assert bot.status == ClientBotStatus.DISCONNECTED


# ============================================================================
# 5. Health Service & Error Recovery Tests
# ============================================================================

@pytest.mark.asyncio
async def test_health_service_unauthorized_token_detection(db_session: AsyncSession, lifecycle_setup):
    bot = lifecycle_setup["bot"]
    health_service = ClientBotHealthService(db_session)

    mock_tg = AsyncMock()
    mock_tg.get_me.side_effect = TelegramInvalidTokenError("401 Unauthorized")

    with patch("app.services.client_bot_health_service.TelegramClient", return_value=mock_tg):
        is_healthy, msg, details = await health_service.check_bot_health(bot.id)

    assert is_healthy is False
    assert details["status"] == ClientBotStatus.INVALID_TOKEN.value
    await db_session.refresh(bot)
    assert bot.status == ClientBotStatus.INVALID_TOKEN


@pytest.mark.asyncio
async def test_health_service_transient_network_error_no_invalidation(db_session: AsyncSession, lifecycle_setup):
    bot = lifecycle_setup["bot"]
    health_service = ClientBotHealthService(db_session)

    mock_tg = AsyncMock()
    mock_tg.get_me.side_effect = TelegramNetworkError("Connection timed out")

    with patch("app.services.client_bot_health_service.TelegramClient", return_value=mock_tg):
        is_healthy, msg, details = await health_service.check_bot_health(bot.id)

    assert is_healthy is False
    assert details["status"] == "NETWORK_ERROR"
    await db_session.refresh(bot)
    # Bot status must remain ACTIVE (not marked INVALID_TOKEN)
    assert bot.status == ClientBotStatus.ACTIVE


@pytest.mark.asyncio
async def test_health_service_recovers_unavailable_bot(db_session: AsyncSession, lifecycle_setup):
    bot = lifecycle_setup["bot"]
    lifecycle_service = ClientBotLifecycleService(db_session)
    health_service = ClientBotHealthService(db_session)

    # Mark bot UNAVAILABLE
    await lifecycle_service.mark_unavailable(bot.id, reason="NETWORK_OUTAGE")
    await db_session.refresh(bot)
    assert bot.status == ClientBotStatus.UNAVAILABLE
    assert bot.desired_status == ClientBotStatus.ACTIVE.value

    # Run health check when Telegram is reachable again
    mock_tg = AsyncMock()
    mock_tg.get_me.return_value = type("BotInfo", (), {"id": bot.telegram_bot_id, "username": "lifecycle_bot"})()

    with patch("app.services.client_bot_health_service.TelegramClient", return_value=mock_tg):
        is_healthy, _, _ = await health_service.check_bot_health(bot.id)

    assert is_healthy is True
    await db_session.refresh(bot)
    assert bot.status == ClientBotStatus.ACTIVE
    assert bot.desired_status is None


# ============================================================================
# 6. Lifecycle Worker Tests
# ============================================================================

@pytest.mark.asyncio
async def test_lifecycle_worker_disconnect_and_resume(db_session: AsyncSession, lifecycle_setup):
    bot = lifecycle_setup["bot"]
    worker = LifecycleWorker(db_session)

    # 1. Test CLIENT_BOT_DISCONNECT job
    job_disc = BackgroundJob(
        job_type=JobType.CLIENT_BOT_DISCONNECT,
        client_bot_id=bot.id,
        payload={"client_bot_id": bot.id},
    )
    db_session.add(job_disc)
    await db_session.flush()

    mock_tg = AsyncMock()
    mock_tg.delete_webhook.return_value = True

    with patch("app.services.client_bot_lifecycle_service.TelegramClient", return_value=mock_tg):
        res = await worker.execute_job(job_disc)

    assert res is True
    assert job_disc.status == JobStatus.COMPLETED
    await db_session.refresh(bot)
    assert bot.status == ClientBotStatus.DISCONNECTED

    # 2. Test CLIENT_BOT_RESUME_WORK job
    job_resume = BackgroundJob(
        job_type=JobType.CLIENT_BOT_RESUME_WORK,
        client_bot_id=bot.id,
        payload={"client_bot_id": bot.id},
    )
    db_session.add(job_resume)
    await db_session.flush()

    res_resume = await worker.execute_job(job_resume)
    assert res_resume is True
    assert job_resume.status == JobStatus.COMPLETED
