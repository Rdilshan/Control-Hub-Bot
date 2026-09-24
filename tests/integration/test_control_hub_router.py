"""Integration tests for ControlHubRouter command routing, guards, and menus."""

from typing import Any, Dict, List, Optional
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.platform_owner import PlatformOwner
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.telegram.control_hub.router import ControlHubRouter


class MockTelegramClient:
    """Mock telegram client to inspect outgoing messages during router execution."""

    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []
        self.edited_messages: List[Dict[str, Any]] = []
        self.answered_callbacks: List[str] = []

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
async def test_non_private_chat_rejected(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    group_update = {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "chat": {"id": -100123456, "type": "group"},
            "from": {"id": 111, "first_name": "Alice"},
            "text": "/start",
        },
    }

    res = await router.process_update(group_update, db_session)
    assert res["action"] == "rejected_non_private"
    assert len(mock_client.sent_messages) == 1
    assert "private" in mock_client.sent_messages[0]["text"].lower()


@pytest.mark.asyncio
async def test_new_client_start_flow(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    update = {
        "update_id": 2,
        "message": {
            "message_id": 11,
            "chat": {"id": 500, "type": "private"},
            "from": {"id": 500, "username": "newbie", "first_name": "Newbie"},
            "text": "/start",
        },
    }

    # 1. First /start -> new client welcome
    res = await router.process_update(update, db_session)
    await db_session.commit()

    assert res["action"] == "new_client_welcome"
    assert len(mock_client.sent_messages) == 1
    assert "Connect My Bot" in str(mock_client.sent_messages[0]["reply_markup"])

    # 2. Second /start without bots -> still returns new client welcome, does NOT duplicate record
    res2 = await router.process_update(update, db_session)
    await db_session.commit()
    assert res2["action"] == "new_client_welcome"


@pytest.mark.asyncio
async def test_existing_client_start_flow(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    # Create client with 1 bot
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    client, _ = await client_repo.get_or_create(telegram_user_id=600, username="pro_client")
    await bot_repo.create_with_defaults(client_id=client.id, telegram_bot_id=9001, token="tok_1")
    await db_session.commit()

    update = {
        "update_id": 3,
        "message": {
            "message_id": 12,
            "chat": {"id": 600, "type": "private"},
            "from": {"id": 600, "username": "pro_client"},
            "text": "/start",
        },
    }

    res = await router.process_update(update, db_session)
    assert res["action"] == "client_home"
    assert "Welcome back to Control Hub" in mock_client.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_owner_start_and_commands(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    # Create active platform owner
    owner = PlatformOwner(telegram_user_id=700, username="boss", is_active=True)
    db_session.add(owner)
    await db_session.commit()

    # /start
    update_start = {
        "update_id": 4,
        "message": {
            "message_id": 13,
            "chat": {"id": 700, "type": "private"},
            "from": {"id": 700, "username": "boss"},
            "text": "/start",
        },
    }
    res = await router.process_update(update_start, db_session)
    assert res["action"] == "owner_home"
    assert "Control Hub" in mock_client.sent_messages[0]["text"]

    # /systemstats as owner
    update_stats = {
        "update_id": 5,
        "message": {
            "message_id": 14,
            "chat": {"id": 700, "type": "private"},
            "from": {"id": 700, "username": "boss"},
            "text": "/systemstats",
        },
    }
    res = await router.process_update(update_stats, db_session)
    assert res["action"] == "owner_systemstats"
    assert "Statistics" in mock_client.sent_messages[1]["text"]



@pytest.mark.asyncio
async def test_unauthorized_owner_command(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    # Normal user attempts /systemstats
    update_stats = {
        "update_id": 6,
        "message": {
            "message_id": 15,
            "chat": {"id": 800, "type": "private"},
            "from": {"id": 800, "username": "hacker"},
            "text": "/systemstats",
        },
    }
    res = await router.process_update(update_stats, db_session)
    assert res["action"] == "unauthorized"
    assert "This command is not available for your account" in mock_client.sent_messages[0]["text"]



@pytest.mark.asyncio
async def test_client_bot_isolation(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)

    # Client A
    client_a, _ = await client_repo.get_or_create(telegram_user_id=901)
    await bot_repo.create_with_defaults(client_id=client_a.id, telegram_bot_id=1001, token="tok_a")
    # Client B
    client_b, _ = await client_repo.get_or_create(telegram_user_id=902)
    await bot_repo.create_with_defaults(client_id=client_b.id, telegram_bot_id=1002, token="tok_b")
    await db_session.commit()

    # Client A executes /mybots
    update_a = {
        "update_id": 7,
        "message": {
            "message_id": 16,
            "chat": {"id": 901, "type": "private"},
            "from": {"id": 901, "username": "client_a"},
            "text": "/mybots",
        },
    }
    await router.process_update(update_a, db_session)
    msg_text = mock_client.sent_messages[0]["text"]
    assert "1001" in msg_text
    assert "1002" not in msg_text


@pytest.mark.asyncio
async def test_callback_navigation(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    cq_update = {
        "update_id": 8,
        "callback_query": {
            "id": "cq_12345",
            "from": {"id": 950, "username": "user_cb"},
            "message": {"message_id": 200, "chat": {"id": 950, "type": "private"}},
            "data": "client:help",
        },
    }

    res = await router.process_update(cq_update, db_session)
    assert res["action"] == "cb_client_help"
    assert "cq_12345" in mock_client.answered_callbacks
    assert len(mock_client.edited_messages) == 1
    assert "Control Hub Help" in mock_client.edited_messages[0]["text"]
