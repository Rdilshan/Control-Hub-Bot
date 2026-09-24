"""Unit tests for ViewerService and subscriber workflows."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import ClientBotStatus, JobStatus, JobType, VideoStatus, ViewerStatus
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_settings import ClientBotSettings
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.db.models.viewer import Viewer
from app.repositories.job import BackgroundJobRepository
from app.repositories.viewer import ViewerRepository
from app.services.viewer_service import ViewerService


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
async def test_viewer_start_new_and_returning(db_session: AsyncSession):
    # 1. Setup client and active bot
    client = Client(telegram_user_id=11001, username="client1")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=555101,
        username="MovieBot",
        display_name="Movie Bot",
        public_id="b_movie123",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    settings = ClientBotSettings(
        client_bot_id=bot.id,
        start_message="🎬 Welcome to MovieBot! Enjoy the show.",
        default_message="❓ Send /help for instructions.",
    )
    db_session.add(settings)
    await db_session.commit()

    mock_tg = MagicMock()
    mock_tg.send_message = AsyncMock(return_value={"message_id": 1})

    viewer_service = ViewerService(db_session)

    # 2. First-time viewer sends /start
    res_new = await viewer_service.handle_viewer_start(
        client_bot=bot,
        telegram_user_id=99001,
        chat_id=99001,
        telegram_client=mock_tg,
        username="viewer_alice",
        first_name="Alice",
    )
    assert res_new["ok"] is True
    assert res_new["action"] == "viewer_start"
    assert res_new["is_new"] is True

    # Verify custom start message was sent
    sent_text = mock_tg.send_message.call_args.kwargs["text"]
    assert "🎬 Welcome to MovieBot!" in sent_text

    # Verify viewer in DB
    viewer_repo = ViewerRepository(db_session)
    v1 = await viewer_repo.get_by_bot_and_telegram_user(bot.id, 99001)
    assert v1 is not None
    assert v1.username == "viewer_alice"
    assert v1.status == ViewerStatus.ACTIVE
    assert v1.first_started_at is not None

    # 3. Returning viewer sends /start with updated name
    res_return = await viewer_service.handle_viewer_start(
        client_bot=bot,
        telegram_user_id=99001,
        chat_id=99001,
        telegram_client=mock_tg,
        username="alice_updated",
        first_name="Alice Updated",
    )
    assert res_return["ok"] is True
    assert res_return["is_new"] is False

    v1_updated = await viewer_repo.get_by_bot_and_telegram_user(bot.id, 99001)
    assert v1_updated.username == "alice_updated"
    assert v1_updated.first_name == "Alice Updated"


@pytest.mark.asyncio
async def test_blocked_viewer_unblocked_on_start(db_session: AsyncSession):
    client = Client(telegram_user_id=11002, username="client2")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=555102,
        username="SeriesBot",
        public_id="b_series123",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    viewer_repo = ViewerRepository(db_session)
    v, _ = await viewer_repo.get_or_create_viewer(
        client_bot_id=bot.id,
        telegram_user_id=88001,
        username="blocked_user",
    )
    await viewer_repo.mark_blocked(bot.id, 88001)
    await db_session.commit()

    assert v.status == ViewerStatus.BLOCKED
    assert v.blocked_at is not None

    mock_tg = MagicMock()
    mock_tg.send_message = AsyncMock(return_value={"message_id": 2})

    viewer_service = ViewerService(db_session)
    res = await viewer_service.handle_viewer_start(
        client_bot=bot,
        telegram_user_id=88001,
        chat_id=88001,
        telegram_client=mock_tg,
    )
    assert res["ok"] is True

    # Check unblocked status
    reloaded = await viewer_repo.get_by_bot_and_telegram_user(bot.id, 88001)
    assert reloaded.status == ViewerStatus.ACTIVE
    assert reloaded.blocked_at is None


@pytest.mark.asyncio
async def test_catchup_job_enqueued_for_eligible_historical_videos(db_session: AsyncSession):
    client = Client(telegram_user_id=11003, username="client3")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=555103,
        username="CatchupBot",
        public_id="b_catchup123",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    # Add 2 READY historical videos
    v1 = Video(
        client_bot_id=bot.id,
        telegram_file_id="f_1",
        telegram_file_unique_id="u_1",
        status=VideoStatus.READY,
    )
    v2 = Video(
        client_bot_id=bot.id,
        telegram_file_id="f_2",
        telegram_file_unique_id="u_2",
        status=VideoStatus.READY,
    )
    db_session.add_all([v1, v2])
    await db_session.commit()

    mock_tg = MagicMock()
    mock_tg.send_message = AsyncMock(return_value={"message_id": 3})

    viewer_service = ViewerService(db_session)

    # New viewer joins
    res = await viewer_service.handle_viewer_start(
        client_bot=bot,
        telegram_user_id=77001,
        chat_id=77001,
        telegram_client=mock_tg,
    )
    assert res["ok"] is True
    assert res["catchup_queued"] is True

    # Verify background job in DB
    job_repo = BackgroundJobRepository(db_session)
    has_job = await job_repo.has_active_catchup_job(bot.id, res["viewer_id"])
    assert has_job is True


@pytest.mark.asyncio
async def test_viewer_help_and_default_reply(db_session: AsyncSession):
    client = Client(telegram_user_id=11004, username="client4")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=555104,
        username="HelpBot",
        public_id="b_help123",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    settings = ClientBotSettings(
        client_bot_id=bot.id,
        default_message="🤖 Fallback reply message from settings.",
    )
    db_session.add(settings)
    await db_session.commit()

    mock_tg = MagicMock()
    mock_tg.send_message = AsyncMock(return_value={"message_id": 4})

    viewer_service = ViewerService(db_session)

    # 1. Test /help
    res_help = await viewer_service.handle_viewer_help(
        client_bot=bot,
        telegram_user_id=66001,
        chat_id=66001,
        telegram_client=mock_tg,
    )
    assert res_help["ok"] is True
    assert "About @HelpBot" in mock_tg.send_message.call_args.kwargs["text"]

    # 2. Test fallback default reply
    res_def = await viewer_service.handle_viewer_default_reply(
        client_bot=bot,
        telegram_user_id=66001,
        chat_id=66001,
        telegram_client=mock_tg,
    )
    assert res_def["ok"] is True
    assert "Fallback reply message from settings" in mock_tg.send_message.call_args.kwargs["text"]
