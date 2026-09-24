"""Unit tests for Client Bot Runtime components."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import BotAdminRole, ClientBotStatus
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.client_bot_settings import ClientBotSettings
from app.telegram.client_bot.actor import extract_telegram_actor
from app.telegram.client_bot.dispatcher import ClientBotDispatcher
from app.telegram.client_bot.factory import ClientBotApiFactory




@pytest.fixture
def sample_message_update():
    return {
        "update_id": 1001,
        "message": {
            "message_id": 1,
            "chat": {"id": 88801, "type": "private"},
            "from": {
                "id": 88801,
                "username": "superfan",
                "first_name": "Super",
                "last_name": "Fan",
                "language_code": "en",
                "is_bot": False,
            },
            "text": "/start",
        },
    }


@pytest.fixture
def sample_callback_update():
    return {
        "update_id": 1002,
        "callback_query": {
            "id": "cb_query_99",
            "from": {"id": 88801, "username": "superfan", "first_name": "Super"},
            "message": {"message_id": 5, "chat": {"id": 88801, "type": "private"}},
            "data": "admin:createvideo",
        },
    }


def test_extract_telegram_actor_message(sample_message_update):
    actor = extract_telegram_actor(sample_message_update)
    assert actor is not None
    assert actor["update_type"] == "message"
    assert actor["telegram_user_id"] == 88801
    assert actor["chat_id"] == 88801
    assert actor["chat_type"] == "private"
    assert actor["username"] == "superfan"
    assert actor["text"] == "/start"
    assert actor["message_id"] == 1


def test_extract_telegram_actor_callback(sample_callback_update):
    actor = extract_telegram_actor(sample_callback_update)
    assert actor is not None
    assert actor["update_type"] == "callback_query"
    assert actor["telegram_user_id"] == 88801
    assert actor["callback_query_id"] == "cb_query_99"
    assert actor["callback_data"] == "admin:createvideo"
    assert actor["message_id"] == 5


def test_extract_telegram_actor_invalid():
    assert extract_telegram_actor({}) is None
    assert extract_telegram_actor({"update_id": 1}) is None


def test_client_bot_api_factory():
    raw_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"
    enc_token = encrypt_token(raw_token)

    factory = ClientBotApiFactory()
    client_1 = factory.get_client(client_bot_id=10, encrypted_token=enc_token)
    assert client_1 is not None
    assert client_1.token == raw_token

    # Verify cached instance
    client_2 = factory.get_client(client_bot_id=10, encrypted_token=enc_token)
    assert client_1 is client_2

    # Invalidate
    factory.invalidate(10)
    client_3 = factory.get_client(client_bot_id=10, encrypted_token=enc_token)
    assert client_3 is not None
    assert client_3 is not client_1


@pytest.mark.asyncio
async def test_dispatcher_guards_and_roles():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        # 1. Setup DB
        client = Client(telegram_user_id=77701, username="owner_user", first_name="Owner")
        session.add(client)
        await session.flush()

        bot = ClientBot(
            client_id=client.id,
            telegram_bot_id=999901,
            username="MovieHubBot",
            display_name="Movie Hub",
            token_encrypted=encrypt_token("999901:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"),
            public_id="b_test123456",
            status=ClientBotStatus.ACTIVE,
        )
        session.add(bot)
        await session.flush()

        # Add Owner as Admin
        admin = ClientBotAdmin(
            client_bot_id=bot.id,
            telegram_user_id=77701,
            username="owner_user",
            first_name="Owner",
            role=BotAdminRole.OWNER,
            is_active=True,
        )
        session.add(admin)
        await session.flush()

        mock_tg = MagicMock()
        mock_tg.send_message = AsyncMock(return_value={"message_id": 10})
        mock_tg.answer_callback_query = AsyncMock(return_value=True)

        dispatcher = ClientBotDispatcher(bot=bot, telegram_client=mock_tg)

        # 2. Test Admin /start -> Receives Admin Dashboard
        admin_update = {
            "update_id": 201,
            "message": {
                "message_id": 1,
                "chat": {"id": 77701, "type": "private"},
                "from": {"id": 77701, "username": "owner_user", "first_name": "Owner"},
                "text": "/start",
            },
        }
        res_admin = await dispatcher.process_update(admin_update, session)
        assert res_admin["action"] == "admin_start"
        assert "Admin Dashboard" in mock_tg.send_message.call_args.kwargs["text"]

        # 3. Test Viewer /start -> Receives Viewer Welcome
        viewer_update = {
            "update_id": 202,
            "message": {
                "message_id": 2,
                "chat": {"id": 88801, "type": "private"},
                "from": {"id": 88801, "username": "viewer_bob", "first_name": "Bob"},
                "text": "/start",
            },
        }
        res_viewer = await dispatcher.process_update(viewer_update, session)
        assert res_viewer["action"] == "viewer_start"
        assert "Welcome to" in mock_tg.send_message.call_args.kwargs["text"]

        # 4. Test Viewer trying Admin Command (/createvideo) -> Rejection
        unauth_update = {
            "update_id": 203,
            "message": {
                "message_id": 3,
                "chat": {"id": 88801, "type": "private"},
                "from": {"id": 88801, "username": "viewer_bob", "first_name": "Bob"},
                "text": "/createvideo",
            },
        }
        res_unauth = await dispatcher.process_update(unauth_update, session)
        assert res_unauth["action"] == "admin_command_rejected_for_viewer"
        assert "Access Denied" in mock_tg.send_message.call_args.kwargs["text"]

        # 5. Test Non-Private Chat -> Rejection
        group_update = {
            "update_id": 204,
            "message": {
                "message_id": 4,
                "chat": {"id": -100123456, "type": "group"},
                "from": {"id": 88801, "username": "viewer_bob"},
                "text": "/start",
            },
        }
        res_grp = await dispatcher.process_update(group_update, session)
        assert res_grp["action"] == "non_private_rejected"
        assert "private 1-on-1 chats" in mock_tg.send_message.call_args.kwargs["text"]

        # 6. Test Paused Bot
        bot.status = ClientBotStatus.PAUSED
        paused_update = {
            "update_id": 205,
            "message": {
                "message_id": 5,
                "chat": {"id": 88801, "type": "private"},
                "from": {"id": 88801, "username": "viewer_bob"},
                "text": "/start",
            },
        }
        res_paused = await dispatcher.process_update(paused_update, session)
        assert res_paused["action"] == "bot_paused"
        assert "paused" in mock_tg.send_message.call_args.kwargs["text"].lower()

    await engine.dispose()
