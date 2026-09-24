"""Integration tests for the complete Video Creation Flow in Client Bots."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import BotAdminRole, ClientBotStatus, ProcessingStatus, VideoStatus
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.sponsor_config import SponsorConfig
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository
from app.telegram.client import TelegramClient
from app.telegram.client_bot.dispatcher import ClientBotDispatcher


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
def mock_tg():
    client = TelegramClient(token="dummy")
    client.send_message = AsyncMock(return_value={"message_id": 100})
    client.answer_callback_query = AsyncMock(return_value=True)
    return client


@pytest.mark.asyncio
async def test_full_video_creation_admin_flow(db_session: AsyncSession, mock_tg: TelegramClient):
    """Verifies complete /createvideo admin interaction, video intake, and sequential creation."""
    # 1. Setup Client, Bot, Admin, and Sponsor
    client = Client(telegram_user_id=7001, username="cinema_admin")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=707070,
        username="CinemaClubBot",
        display_name="Cinema Club",
        public_id="b_cinemaclub",
        token_encrypted=encrypt_token("707070:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    admin = ClientBotAdmin(
        client_bot_id=bot.id,
        telegram_user_id=7001,
        username="cinema_admin",
        role=BotAdminRole.OWNER,
        is_active=True,
    )
    sponsor = SponsorConfig(
        client_bot_id=bot.id,
        is_enabled=True,
        sponsor_url="https://unlockify.ink/stream",
        button_text="🔓 Unlock Full Movie",
    )
    db_session.add_all([admin, sponsor])
    await db_session.commit()

    dispatcher = ClientBotDispatcher(bot=bot, telegram_client=mock_tg)

    # 2. Step 1: Admin sends /createvideo
    res_start = await dispatcher.process_update(
        update={
            "update_id": 801,
            "message": {
                "message_id": 1,
                "chat": {"id": 7001, "type": "private"},
                "from": {"id": 7001, "username": "cinema_admin"},
                "text": "/createvideo",
            },
        },
        session=db_session,
    )
    assert res_start["action"] == "create_video_prompt_sent"
    assert "send <b>ONE</b> Telegram video" in mock_tg.send_message.call_args.kwargs["text"]

    # 3. Step 2: Admin sends Telegram Video 1
    res_vid1 = await dispatcher.process_update(
        update={
            "update_id": 802,
            "message": {
                "message_id": 2,
                "chat": {"id": 7001, "type": "private"},
                "from": {"id": 7001, "username": "cinema_admin"},
                "caption": "Part 1: The Beginning",
                "video": {
                    "file_id": "file_vid_111",
                    "file_unique_id": "uniq_111",
                    "file_size": 50000000,
                    "duration": 600,
                    "width": 1920,
                    "height": 1080,
                    "file_name": "part1.mp4",
                },
            },
        },
        session=db_session,
    )
    assert res_vid1["action"] == "video_created"
    assert "Video Received" in mock_tg.send_message.call_args.kwargs["text"]

    # 4. Step 3: Admin immediately starts /createvideo for Video 2
    res_start2 = await dispatcher.process_update(
        update={
            "update_id": 803,
            "message": {
                "message_id": 3,
                "chat": {"id": 7001, "type": "private"},
                "from": {"id": 7001, "username": "cinema_admin"},
                "text": "/createvideo",
            },
        },
        session=db_session,
    )
    assert res_start2["action"] == "create_video_prompt_sent"

    # 5. Step 4: Admin sends Video 2
    res_vid2 = await dispatcher.process_update(
        update={
            "update_id": 804,
            "message": {
                "message_id": 4,
                "chat": {"id": 7001, "type": "private"},
                "from": {"id": 7001, "username": "cinema_admin"},
                "caption": "Part 2: The Climax",
                "video": {
                    "file_id": "file_vid_222",
                    "file_unique_id": "uniq_222",
                    "file_size": 65000000,
                    "duration": 720,
                    "width": 1920,
                    "height": 1080,
                    "file_name": "part2.mp4",
                },
            },
        },
        session=db_session,
    )
    assert res_vid2["action"] == "video_created"

    # 6. Verify Database: Both videos exist and are in RECEIVED status
    video_repo = VideoRepository(db_session)
    videos = await video_repo.list_by_bot(bot.id)
    assert len(videos) == 2
    assert videos[0].caption == "Part 2: The Climax"
    assert videos[1].caption == "Part 1: The Beginning"
    assert videos[0].status == VideoStatus.RECEIVED
    assert videos[1].status == VideoStatus.RECEIVED

    # 7. Step 5: Admin runs /videos
    res_videos = await dispatcher.process_update(
        update={
            "update_id": 805,
            "message": {
                "message_id": 5,
                "chat": {"id": 7001, "type": "private"},
                "from": {"id": 7001, "username": "cinema_admin"},
                "text": "/videos",
            },
        },
        session=db_session,
    )
    assert res_videos["action"] == "admin_videos_list"
    assert "Video Library" in mock_tg.send_message.call_args.kwargs["text"]
    assert "Part 2: The Climax" in mock_tg.send_message.call_args.kwargs["text"]

    # 8. Step 6: Admin runs /processing
    res_proc = await dispatcher.process_update(
        update={
            "update_id": 806,
            "message": {
                "message_id": 6,
                "chat": {"id": 7001, "type": "private"},
                "from": {"id": 7001, "username": "cinema_admin"},
                "text": "/processing",
            },
        },
        session=db_session,
    )
    assert res_proc["action"] == "admin_processing_list"
    assert "Processing Queue" in mock_tg.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_multi_bot_video_isolation(db_session: AsyncSession, mock_tg: TelegramClient):
    """Section 121: Videos created in Bot A do not leak or appear in Bot B."""
    client = Client(telegram_user_id=7002, username="cinema_admin2")
    db_session.add(client)
    await db_session.flush()

    bot_a = ClientBot(
        client_id=client.id,
        telegram_bot_id=808081,
        username="BotA",
        public_id="b_bota",
        status=ClientBotStatus.ACTIVE,
    )
    bot_b = ClientBot(
        client_id=client.id,
        telegram_bot_id=808082,
        username="BotB",
        public_id="b_botb",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add_all([bot_a, bot_b])
    await db_session.flush()

    admin_a = ClientBotAdmin(client_bot_id=bot_a.id, telegram_user_id=7002, role=BotAdminRole.OWNER, is_active=True)
    admin_b = ClientBotAdmin(client_bot_id=bot_b.id, telegram_user_id=7002, role=BotAdminRole.OWNER, is_active=True)
    sponsor_a = SponsorConfig(client_bot_id=bot_a.id, is_enabled=True, sponsor_url="https://unlockify.ink/a")
    sponsor_b = SponsorConfig(client_bot_id=bot_b.id, is_enabled=True, sponsor_url="https://unlockify.ink/b")
    db_session.add_all([admin_a, admin_b, sponsor_a, sponsor_b])
    await db_session.commit()

    dispatcher_a = ClientBotDispatcher(bot=bot_a, telegram_client=mock_tg)
    dispatcher_b = ClientBotDispatcher(bot=bot_b, telegram_client=mock_tg)

    # Start creation in Bot A
    await dispatcher_a.process_update(
        update={"update_id": 901, "message": {"message_id": 1, "chat": {"id": 7002, "type": "private"}, "from": {"id": 7002}, "text": "/createvideo"}},
        session=db_session,
    )

    # Send video in Bot A
    res_a = await dispatcher_a.process_update(
        update={
            "update_id": 902,
            "message": {
                "message_id": 2,
                "chat": {"id": 7002, "type": "private"},
                "from": {"id": 7002},
                "caption": "Bot A Exclusive",
                "video": {"file_id": "file_a_1", "file_unique_id": "uniq_a_1"},
            },
        },
        session=db_session,
    )
    assert res_a["action"] == "video_created"

    # Check Bot A has 1 video and Bot B has 0 videos
    video_repo = VideoRepository(db_session)
    videos_a = await video_repo.list_by_bot(bot_a.id)
    videos_b = await video_repo.list_by_bot(bot_b.id)
    assert len(videos_a) == 1
    assert len(videos_b) == 0
    assert videos_a[0].caption == "Bot A Exclusive"
