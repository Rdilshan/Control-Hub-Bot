"""Integration tests for the complete Client Onboarding flow in Control Hub Bot."""

from typing import Any, Dict, List, Optional
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import ClientStatus
from app.db.base import Base
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.telegram.control_hub.router import ControlHubRouter


class MockTelegramClient:
    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []
        self.edited_messages: List[Dict[str, Any]] = []
        self.answered_callbacks: List[str] = []

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        return True

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        call = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        }
        self.sent_messages.append(call)
        return {"message_id": 999, "chat": {"id": chat_id}, "text": text}

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        call = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        }
        self.edited_messages.append(call)
        return {"message_id": message_id, "chat": {"id": chat_id}, "text": text}

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> bool:
        self.answered_callbacks.append(callback_query_id)
        return True


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_new_client_complete_onboarding_journey(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    # 1. New user sends /start
    start_update = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": 5001, "type": "private"},
            "from": {"id": 5001, "username": "bob", "first_name": "Bob"},
            "text": "/start",
        },
    }
    res = await router.process_update(start_update, db_session)
    await db_session.commit()

    assert res["action"] == "new_client_welcome"
    assert "Welcome to Control Hub" in mock_client.sent_messages[0]["text"]
    assert "Connect My Bot" in str(mock_client.sent_messages[0]["reply_markup"])

    # 2. User taps "How It Works"
    cb_how = {
        "update_id": 2,
        "callback_query": {
            "id": "cq_1",
            "from": {"id": 5001, "username": "bob"},
            "message": {"message_id": 1, "chat": {"id": 5001, "type": "private"}},
            "data": "client:how_it_works",
        },
    }
    await router.process_update(cb_how, db_session)
    assert "How Control Hub Works" in mock_client.edited_messages[0]["text"]

    # 3. User taps "Connect My Bot" -> BotFather guide
    cb_connect = {
        "update_id": 3,
        "callback_query": {
            "id": "cq_2",
            "from": {"id": 5001, "username": "bob"},
            "message": {"message_id": 1, "chat": {"id": 5001, "type": "private"}},
            "data": "client:connectbot",
        },
    }
    await router.process_update(cb_connect, db_session)
    assert "Connect a Telegram Bot" in mock_client.edited_messages[1]["text"]
    assert "Bot Token Security" in mock_client.edited_messages[1]["text"]

    # 4. User taps "I Have My Token" -> Token prompt
    cb_token_ready = {
        "update_id": 4,
        "callback_query": {
            "id": "cq_3",
            "from": {"id": 5001, "username": "bob"},
            "message": {"message_id": 1, "chat": {"id": 5001, "type": "private"}},
            "data": "client:connect:token_ready",
        },
    }
    await router.process_update(cb_token_ready, db_session)
    assert "Submit Bot Token" in mock_client.edited_messages[2]["text"]

    # 5. User sends Bot token
    from unittest.mock import patch, AsyncMock
    from app.telegram.types import TelegramBotInfo

    token_update = {
        "update_id": 5,
        "message": {
            "message_id": 2,
            "chat": {"id": 5001, "type": "private"},
            "from": {"id": 5001, "username": "bob"},
            "text": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz_1234567",
        },
    }
    with patch("app.telegram.client.TelegramClient.get_me", new_callable=AsyncMock) as mock_get_me:
        mock_get_me.return_value = TelegramBotInfo(id=123456789, is_bot=True, first_name="Bob Bot", username="BobBot")
        res_tok = await router.process_update(token_update, db_session)
        assert res_tok["action"] == "bot_found_confirm"
        assert "Bob Bot" in mock_client.sent_messages[1]["text"]


@pytest.mark.asyncio
async def test_returning_client_home_and_mybots_flow(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)

    # Setup returning client with 2 bots
    client, _ = await client_repo.get_or_create(telegram_user_id=6001, username="pro_manager")
    b1 = await bot_repo.create_with_defaults(
        client_id=client.id, telegram_bot_id=1111, token="tok_1", username="MovieBot"
    )
    b2 = await bot_repo.create_with_defaults(
        client_id=client.id, telegram_bot_id=2222, token="tok_2", username="SeriesBot"
    )
    await db_session.commit()

    # 1. Returning client sends /start
    start_update = {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "chat": {"id": 6001, "type": "private"},
            "from": {"id": 6001, "username": "pro_manager"},
            "text": "/start",
        },
    }
    res = await router.process_update(start_update, db_session)
    assert res["action"] == "client_home"
    assert "You have <b>2</b> connected bot(s)" in mock_client.sent_messages[0]["text"]

    # 2. Client uses /mybots
    mybots_update = {
        "update_id": 2,
        "message": {
            "message_id": 11,
            "chat": {"id": 6001, "type": "private"},
            "from": {"id": 6001, "username": "pro_manager"},
            "text": "/mybots",
        },
    }
    await router.process_update(mybots_update, db_session)
    msg_text = mock_client.sent_messages[1]["text"]
    assert "@MovieBot" in msg_text
    assert "@SeriesBot" in msg_text

    # 3. Client views detail of MovieBot
    cb_view = {
        "update_id": 3,
        "callback_query": {
            "id": "cq_view",
            "from": {"id": 6001, "username": "pro_manager"},
            "message": {"message_id": 11, "chat": {"id": 6001, "type": "private"}},
            "data": f"client:bot:view:{b1.id}",
        },
    }
    await router.process_update(cb_view, db_session)
    assert "Bot: @MovieBot" in mock_client.edited_messages[0]["text"]

    # 4. Client disconnects MovieBot
    cb_disc = {
        "update_id": 4,
        "callback_query": {
            "id": "cq_disc",
            "from": {"id": 6001, "username": "pro_manager"},
            "message": {"message_id": 11, "chat": {"id": 6001, "type": "private"}},
            "data": f"client:bot:disconnect:{b1.id}",
        },
    }
    await router.process_update(cb_disc, db_session)
    assert "Disconnect @MovieBot?" in mock_client.edited_messages[1]["text"]

    # 5. Client confirms disconnect
    cb_disc_confirm = {
        "update_id": 5,
        "callback_query": {
            "id": "cq_disc_confirm",
            "from": {"id": 6001, "username": "pro_manager"},
            "message": {"message_id": 11, "chat": {"id": 6001, "type": "private"}},
            "data": f"client:bot:disconnect_confirm:{b1.id}",
        },
    }
    await router.process_update(cb_disc_confirm, db_session)
    await db_session.commit()
    assert "has been disconnected" in mock_client.edited_messages[2]["text"]


@pytest.mark.asyncio
async def test_cross_client_bot_access_blocked(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)

    c1, _ = await client_repo.get_or_create(telegram_user_id=7001, username="client_1")
    c2, _ = await client_repo.get_or_create(telegram_user_id=7002, username="client_2")

    bot2 = await bot_repo.create_with_defaults(client_id=c2.id, telegram_bot_id=9999, token="tok_2")
    await db_session.commit()

    # Client 1 crafts callback to view Client 2's bot
    cb_hack = {
        "update_id": 1,
        "callback_query": {
            "id": "cq_hack",
            "from": {"id": 7001, "username": "client_1"},
            "message": {"message_id": 50, "chat": {"id": 7001, "type": "private"}},
            "data": f"client:bot:view:{bot2.id}",
        },
    }
    res = await router.process_update(cb_hack, db_session)
    assert res["action"] == "client_bot_not_found"
    assert "Bot not found" in mock_client.edited_messages[0]["text"]


@pytest.mark.asyncio
async def test_suspended_and_disabled_client_guards(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    client_repo = ClientRepository(db_session)
    c, _ = await client_repo.get_or_create(telegram_user_id=8001, username="bad_user")
    await client_repo.suspend(c.id)
    await db_session.commit()

    # Suspended client tries /start
    res = await router.process_update(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": 8001, "type": "private"},
                "from": {"id": 8001, "username": "bad_user"},
                "text": "/start",
            },
        },
        db_session,
    )
    assert res["action"] == "client_suspended"
    assert "temporarily suspended" in mock_client.sent_messages[0]["text"]

    # Suspended client tries /connectbot
    res2 = await router.process_update(
        {
            "update_id": 2,
            "message": {
                "message_id": 2,
                "chat": {"id": 8001, "type": "private"},
                "from": {"id": 8001, "username": "bad_user"},
                "text": "/connectbot",
            },
        },
        db_session,
    )
    assert res2["action"] == "client_suspended"
