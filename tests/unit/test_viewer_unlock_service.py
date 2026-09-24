"""Unit tests for ViewerUnlockService, ClientBotSponsorService, and TelegramUnlockDestinationService."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
    ClientBotStatus,
    DeliveryStatus,
    VideoStatus,
    ViewerStatus,
)
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.sponsor_config import SponsorConfig
from app.db.models.video import Video
from app.db.models.viewer import Viewer
from app.exceptions import (
    NotFoundError,
    ValidationError,
)
from app.repositories.video import VideoRepository
from app.repositories.video_delivery import VideoDeliveryRepository
from app.repositories.viewer import ViewerRepository
from app.services.client_bot_sponsor_service import ClientBotSponsorService
from app.services.telegram_unlock_destination_service import TelegramUnlockDestinationService
from app.services.video_delivery_service import VideoDeliveryService
from app.services.viewer_unlock_service import ViewerUnlockService
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramAPIError, TelegramForbiddenError, TelegramInvalidTokenError, TelegramNetworkError


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


# ---------------------------------------------------------
# 1. TelegramUnlockDestinationService Tests
# ---------------------------------------------------------
def test_telegram_unlock_destination_service():
    service = TelegramUnlockDestinationService()

    # Build destination
    dest = service.build_destination(bot_username="@MovieWorldBot", video_public_id="vid_abc123")
    assert dest == "https://t.me/MovieWorldBot?start=unlock_vid_abc123"

    # Is unlock payload
    assert service.is_unlock_payload("unlock_vid_abc123") is True
    assert service.is_unlock_payload("start_normal") is False
    assert service.is_unlock_payload("") is False

    # Parse payload
    assert service.parse_payload("unlock_vid_abc123") == "vid_abc123"
    assert service.parse_payload("unlock_") is None
    assert service.parse_payload("other_payload") is None
    assert service.parse_payload(None) is None


# ---------------------------------------------------------
# 2. ClientBotSponsorService Tests
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_client_bot_sponsor_service(db_session: AsyncSession):
    client = Client(telegram_user_id=1001, username="sponsor_owner")
    db_session.add(client)
    await db_session.flush()

    bot1 = ClientBot(
        client_id=client.id,
        telegram_bot_id=11111,
        username="BotOne",
        public_id="bot_one_pub",
        status=ClientBotStatus.ACTIVE,
    )
    bot2 = ClientBot(
        client_id=client.id,
        telegram_bot_id=22222,
        username="BotTwo",
        public_id="bot_two_pub",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add_all([bot1, bot2])
    await db_session.flush()

    service = ClientBotSponsorService(db_session)

    # 1. URL validation tests
    assert service.validate_sponsor_url("https://sponsor.example/ad1") == "https://sponsor.example/ad1"
    assert service.validate_sponsor_url("http://ad.example/link") == "http://ad.example/link"

    with pytest.raises(ValidationError):
        service.validate_sponsor_url("javascript:alert(1)")
    with pytest.raises(ValidationError):
        service.validate_sponsor_url("ftp://server.example")
    with pytest.raises(ValidationError):
        service.validate_sponsor_url("")

    # 2. Bot isolation: Set Bot 1 sponsor
    s1 = await service.set_sponsor_url(bot1.id, "https://bot1-ad.example/offer")
    assert s1.client_bot_id == bot1.id
    assert s1.is_enabled is True
    assert s1.sponsor_url == "https://bot1-ad.example/offer"

    # Bot 2 has no sponsor yet
    s2 = await service.get_sponsor(bot2.id)
    assert s2 is None

    # Set Bot 2 sponsor
    s2 = await service.set_sponsor_url(bot2.id, "https://bot2-ad.example/deal")
    assert s2.sponsor_url == "https://bot2-ad.example/deal"

    # 3. Disable Bot 1 sponsor
    await service.disable_sponsor(bot1.id)
    await db_session.refresh(s1)
    assert s1.is_enabled is False

    # Enable Bot 1 sponsor
    await service.enable_sponsor(bot1.id)
    await db_session.refresh(s1)
    assert s1.is_enabled is True


# ---------------------------------------------------------
# 3. ViewerUnlockService & VideoDeliveryService Tests
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_viewer_unlock_service_valid_delivery(db_session: AsyncSession):
    client = Client(telegram_user_id=2001, username="unlock_owner")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=33333,
        username="CinemaDeliveryBot",
        public_id="bot_cinema_del",
        token_encrypted=encrypt_token("33333:BOT_TOKEN_DELIVERY"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    video_repo = VideoRepository(db_session)
    vid = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="tg_vid_file_real_555",
        telegram_file_unique_id="uniq_555",
        caption="Action Blockbuster 2026",
    )
    # Mark video READY
    await video_repo.mark_ready(vid.id, bot.id)
    await db_session.commit()

    mock_tg = MagicMock(spec=TelegramClient)
    mock_tg.send_message = AsyncMock(return_value={"message_id": 1})
    mock_tg.send_video = AsyncMock(return_value={"message_id": 9901})

    with patch("app.telegram.client.TelegramClient.send_video", new_callable=AsyncMock) as mock_send_vid:
        mock_send_vid.return_value = {"message_id": 9901}

        service = ViewerUnlockService(db_session)
        res = await service.handle_unlock_request(
            client_bot=bot,
            telegram_user_id=777888,
            chat_id=777888,
            payload=f"unlock_{vid.public_id}",
            actor_data={"username": "happy_viewer", "first_name": "Happy"},
            telegram_client=mock_tg,
        )

        assert res["ok"] is True
        assert res["status"] == "SENT"
        assert res["message_id"] == 9901

        # Check Delivery Record in DB
        delivery_repo = VideoDeliveryRepository(db_session)
        count = await delivery_repo.count_by_video(vid.id, status=DeliveryStatus.SENT)
        assert count == 1

        # Check Viewer record was created and ACTIVE
        viewer_repo = ViewerRepository(db_session)
        viewer = await viewer_repo.get_by_bot_and_telegram_user(bot.id, 777888)
        assert viewer is not None
        assert viewer.status == ViewerStatus.ACTIVE
        assert viewer.username == "happy_viewer"


@pytest.mark.asyncio
async def test_viewer_unlock_service_cross_bot_rejection(db_session: AsyncSession):
    """Section 23, 93: Video of Bot A requested via Bot B is rejected without leaking data."""
    client = Client(telegram_user_id=2002, username="cross_owner")
    db_session.add(client)
    await db_session.flush()

    bot_a = ClientBot(
        client_id=client.id,
        telegram_bot_id=44401,
        username="BotA",
        public_id="bot_a_pub",
        token_encrypted=encrypt_token("tok_a"),
        status=ClientBotStatus.ACTIVE,
    )
    bot_b = ClientBot(
        client_id=client.id,
        telegram_bot_id=44402,
        username="BotB",
        public_id="bot_b_pub",
        token_encrypted=encrypt_token("tok_b"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add_all([bot_a, bot_b])
    await db_session.flush()

    video_repo = VideoRepository(db_session)
    vid_a = await video_repo.create_video(
        client_bot_id=bot_a.id,
        telegram_file_id="tg_vid_bot_a",
        telegram_file_unique_id="uniq_bot_a",
    )
    await video_repo.mark_ready(vid_a.id, bot_a.id)
    await db_session.commit()

    mock_tg = MagicMock(spec=TelegramClient)
    mock_tg.send_message = AsyncMock(return_value={"message_id": 1})

    service = ViewerUnlockService(db_session)
    # User calls Bot B with Bot A's video public_id
    res = await service.handle_unlock_request(
        client_bot=bot_b,
        telegram_user_id=999111,
        chat_id=999111,
        payload=f"unlock_{vid_a.public_id}",
        actor_data={"username": "attacker"},
        telegram_client=mock_tg,
    )

    assert res["ok"] is False
    assert res["error"] == "video_not_found"
    assert "This video is not available" in mock_tg.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_viewer_unlock_service_video_not_ready_or_disabled(db_session: AsyncSession):
    client = Client(telegram_user_id=2003, username="guard_owner")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=55501,
        username="GuardBot",
        public_id="bot_guard_pub",
        token_encrypted=encrypt_token("tok_guard"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    video_repo = VideoRepository(db_session)
    # 1. Video not ready (RECEIVED)
    vid_unready = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="vid_unready_file",
        telegram_file_unique_id="uniq_unready",
    )

    # 2. Video disabled
    vid_disabled = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="vid_disabled_file",
        telegram_file_unique_id="uniq_disabled",
    )
    await video_repo.update_status(vid_disabled.id, VideoStatus.DISABLED)
    await db_session.commit()

    mock_tg = MagicMock(spec=TelegramClient)
    mock_tg.send_message = AsyncMock(return_value={"message_id": 1})

    service = ViewerUnlockService(db_session)

    # Test unready video
    res_unready = await service.handle_unlock_request(
        client_bot=bot,
        telegram_user_id=888111,
        chat_id=888111,
        payload=f"unlock_{vid_unready.public_id}",
        actor_data={},
        telegram_client=mock_tg,
    )
    assert res_unready["ok"] is False
    assert res_unready["error"] == "video_not_ready"
    assert "not ready yet" in mock_tg.send_message.call_args.kwargs["text"]

    # Test disabled video
    res_disabled = await service.handle_unlock_request(
        client_bot=bot,
        telegram_user_id=888111,
        chat_id=888111,
        payload=f"unlock_{vid_disabled.public_id}",
        actor_data={},
        telegram_client=mock_tg,
    )
    assert res_disabled["ok"] is False
    assert res_disabled["error"] == "video_disabled"
    assert "no longer available" in mock_tg.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_viewer_unlock_service_paused_bot(db_session: AsyncSession):
    client = Client(telegram_user_id=2004, username="paused_owner")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=66601,
        username="PausedBot",
        public_id="bot_paused_pub",
        token_encrypted=encrypt_token("tok_paused"),
        status=ClientBotStatus.PAUSED,
    )
    db_session.add(bot)
    await db_session.flush()

    video_repo = VideoRepository(db_session)
    vid = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="vid_paused_file",
        telegram_file_unique_id="uniq_paused",
    )
    await video_repo.mark_ready(vid.id, bot.id)
    await db_session.commit()

    mock_tg = MagicMock(spec=TelegramClient)
    mock_tg.send_message = AsyncMock(return_value={"message_id": 1})

    service = ViewerUnlockService(db_session)
    res = await service.handle_unlock_request(
        client_bot=bot,
        telegram_user_id=777222,
        chat_id=777222,
        payload=f"unlock_{vid.public_id}",
        actor_data={},
        telegram_client=mock_tg,
    )
    assert res["ok"] is False
    assert res["error"] == "bot_paused"
    assert "paused" in mock_tg.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_viewer_unlock_service_blocked_viewer_handling(db_session: AsyncSession):
    """Section 31, 99: When user blocked the bot, marks delivery BLOCKED and viewer BLOCKED."""
    client = Client(telegram_user_id=2005, username="blocked_owner")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=77701,
        username="BlockedBot",
        public_id="bot_blocked_pub",
        token_encrypted=encrypt_token("tok_blocked"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    video_repo = VideoRepository(db_session)
    vid = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="vid_blocked_file",
        telegram_file_unique_id="uniq_blocked",
    )
    await video_repo.mark_ready(vid.id, bot.id)
    await db_session.commit()

    mock_tg = MagicMock(spec=TelegramClient)

    with patch(
        "app.telegram.client.TelegramClient.send_video",
        side_effect=TelegramForbiddenError("Forbidden: bot was blocked by the user"),
    ):
        service = ViewerUnlockService(db_session)
        res = await service.handle_unlock_request(
            client_bot=bot,
            telegram_user_id=888333,
            chat_id=888333,
            payload=f"unlock_{vid.public_id}",
            actor_data={"username": "blocked_user"},
            telegram_client=mock_tg,
        )

        assert res["ok"] is False
        assert res["status"] == "BLOCKED"

        # Check Viewer status in DB is BLOCKED
        viewer_repo = ViewerRepository(db_session)
        viewer = await viewer_repo.get_by_bot_and_telegram_user(bot.id, 888333)
        assert viewer.status == ViewerStatus.BLOCKED


@pytest.mark.asyncio
async def test_viewer_unlock_service_repeat_unlock(db_session: AsyncSession):
    """Section 36, 95: Repeated unlock requests by same user deliver video multiple times without crash."""
    client = Client(telegram_user_id=2006, username="repeat_owner")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=88801,
        username="RepeatBot",
        public_id="bot_repeat_pub",
        token_encrypted=encrypt_token("tok_repeat"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    video_repo = VideoRepository(db_session)
    vid = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="vid_repeat_file",
        telegram_file_unique_id="uniq_repeat",
    )
    await video_repo.mark_ready(vid.id, bot.id)
    await db_session.commit()

    mock_tg = MagicMock(spec=TelegramClient)

    with patch("app.telegram.client.TelegramClient.send_video", new_callable=AsyncMock) as mock_send_vid:
        mock_send_vid.return_value = {"message_id": 1001}

        service = ViewerUnlockService(db_session)

        # 1st request
        res1 = await service.handle_unlock_request(
            client_bot=bot,
            telegram_user_id=999444,
            chat_id=999444,
            payload=f"unlock_{vid.public_id}",
            actor_data={"username": "repeat_viewer"},
            telegram_client=mock_tg,
        )
        assert res1["ok"] is True

        # 2nd request
        res2 = await service.handle_unlock_request(
            client_bot=bot,
            telegram_user_id=999444,
            chat_id=999444,
            payload=f"unlock_{vid.public_id}",
            actor_data={"username": "repeat_viewer"},
            telegram_client=mock_tg,
        )
        assert res2["ok"] is True

        delivery_repo = VideoDeliveryRepository(db_session)
        count = await delivery_repo.count_by_video(vid.id, status=DeliveryStatus.SENT)
        assert count == 2
