"""Integration tests for the complete Viewer User Journey across Client Bots."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import BotAdminRole, ClientBotStatus, VideoStatus, ViewerStatus
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.client_bot_settings import ClientBotSettings
from app.db.models.video import Video
from app.db.models.viewer import Viewer
from app.repositories.viewer import ViewerRepository
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
async def test_complete_viewer_user_journey(db_session: AsyncSession, mock_tg: TelegramClient):
    """Verifies complete viewer lifecycle: join, welcome, help, default fallback, and multi-bot isolation."""
    # 1. Setup Bot A (MovieBot) and Bot B (SeriesBot) under Client 1
    client = Client(telegram_user_id=1001, username="studio_owner")
    db_session.add(client)
    await db_session.flush()

    bot_a = ClientBot(
        client_id=client.id,
        telegram_bot_id=101010,
        username="MovieWorldBot",
        display_name="Movie World",
        public_id="b_movieworld",
        token_encrypted=encrypt_token("101010:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"),
        status=ClientBotStatus.ACTIVE,
    )
    bot_b = ClientBot(
        client_id=client.id,
        telegram_bot_id=202020,
        username="SeriesHubBot",
        display_name="Series Hub",
        public_id="b_serieshub",
        token_encrypted=encrypt_token("202020:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add_all([bot_a, bot_b])
    await db_session.flush()

    # Add Owner Admin for both bots
    admin_a = ClientBotAdmin(
        client_bot_id=bot_a.id,
        telegram_user_id=1001,
        role=BotAdminRole.OWNER,
        is_active=True,
    )
    admin_b = ClientBotAdmin(
        client_bot_id=bot_b.id,
        telegram_user_id=1001,
        role=BotAdminRole.OWNER,
        is_active=True,
    )
    db_session.add_all([admin_a, admin_b])

    # Add custom settings for Bot A
    settings_a = ClientBotSettings(
        client_bot_id=bot_a.id,
        start_message="🍿 Welcome to Movie World! Best HD movies await.",
        default_message="🍿 Use /help to see how to stream movies.",
    )
    db_session.add(settings_a)
    await db_session.commit()

    dispatcher_a = ClientBotDispatcher(bot=bot_a, telegram_client=mock_tg)
    dispatcher_b = ClientBotDispatcher(bot=bot_b, telegram_client=mock_tg)

    user_bob = 55001

    # 2. Bob sends /start to Bot A -> Receives Bot A custom start message
    res_start_a = await dispatcher_a.process_update(
        update={
            "update_id": 9101,
            "message": {
                "message_id": 1,
                "chat": {"id": user_bob, "type": "private"},
                "from": {"id": user_bob, "username": "bob55", "first_name": "Bob"},
                "text": "/start",
            },
        },
        session=db_session,
    )
    assert res_start_a["action"] == "viewer_start"
    assert "🍿 Welcome to Movie World!" in mock_tg.send_message.call_args.kwargs["text"]

    # 3. Bob sends /help to Bot A -> Receives help message
    res_help_a = await dispatcher_a.process_update(
        update={
            "update_id": 9102,
            "message": {
                "message_id": 2,
                "chat": {"id": user_bob, "type": "private"},
                "from": {"id": user_bob, "username": "bob55", "first_name": "Bob"},
                "text": "/help",
            },
        },
        session=db_session,
    )
    assert res_help_a["action"] == "viewer_help"
    assert "About @MovieWorldBot" in mock_tg.send_message.call_args.kwargs["text"]

    # 4. Bob sends random message to Bot A -> Receives Bot A custom default fallback
    res_msg_a = await dispatcher_a.process_update(
        update={
            "update_id": 9103,
            "message": {
                "message_id": 3,
                "chat": {"id": user_bob, "type": "private"},
                "from": {"id": user_bob, "username": "bob55", "first_name": "Bob"},
                "text": "when is new movie coming?",
            },
        },
        session=db_session,
    )
    assert res_msg_a["action"] == "viewer_default_reply"
    assert "🍿 Use /help to see how to stream" in mock_tg.send_message.call_args.kwargs["text"]

    # 5. Bob sends /start to Bot B -> Created as separate viewer under Bot B
    res_start_b = await dispatcher_b.process_update(
        update={
            "update_id": 9104,
            "message": {
                "message_id": 1,
                "chat": {"id": user_bob, "type": "private"},
                "from": {"id": user_bob, "username": "bob55", "first_name": "Bob"},
                "text": "/start",
            },
        },
        session=db_session,
    )
    assert res_start_b["action"] == "viewer_start"

    # Verify separate viewer rows in DB
    viewer_repo = ViewerRepository(db_session)
    v_a = await viewer_repo.get_by_bot_and_telegram_user(bot_a.id, user_bob)
    v_b = await viewer_repo.get_by_bot_and_telegram_user(bot_b.id, user_bob)
    assert v_a is not None
    assert v_b is not None
    assert v_a.id != v_b.id
    assert v_a.client_bot_id == bot_a.id
    assert v_b.client_bot_id == bot_b.id

    # 6. Admin user (1001) sends /start to Bot A -> Routes to Admin Dashboard (Not added to viewers)
    res_admin = await dispatcher_a.process_update(
        update={
            "update_id": 9105,
            "message": {
                "message_id": 10,
                "chat": {"id": 1001, "type": "private"},
                "from": {"id": 1001, "username": "studio_owner", "first_name": "Studio"},
                "text": "/start",
            },
        },
        session=db_session,
    )
    assert res_admin["action"] == "admin_start"
    admin_viewer = await viewer_repo.get_by_bot_and_telegram_user(bot_a.id, 1001)
    assert admin_viewer is None  # Admin is isolated from viewers table
