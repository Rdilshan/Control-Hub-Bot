"""Integration tests for the complete Platform Owner flow in Control Hub Bot."""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import ClientStatus, JobStatus, JobType
from app.db.base import Base
from app.db.models.platform_owner import PlatformOwner
from app.repositories.broadcast import BroadcastRepository
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.repositories.job import BackgroundJobRepository
from app.telegram.control_hub.router import ControlHubRouter


class MockTelegramClient:
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
async def test_owner_clients_management_flow(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    # 1. Setup Platform Owner & a Client
    owner = PlatformOwner(telegram_user_id=100, username="boss", is_active=True)
    db_session.add(owner)
    client_repo = ClientRepository(db_session)
    client_a, _ = await client_repo.get_or_create(telegram_user_id=200, username="client_alpha")
    await db_session.commit()

    # 2. Owner executes /clients
    cmd_update = {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "chat": {"id": 100, "type": "private"},
            "from": {"id": 100, "username": "boss"},
            "text": "/clients",
        },
    }
    await router.process_update(cmd_update, db_session)
    assert len(mock_client.sent_messages) == 1
    assert "Clients Overview" in mock_client.sent_messages[0]["text"]

    # 3. Owner clicks "View Clients" -> callback owner:clients:page:1
    cb_list = {
        "update_id": 2,
        "callback_query": {
            "id": "cq_1",
            "from": {"id": 100, "username": "boss"},
            "message": {"message_id": 10, "chat": {"id": 100, "type": "private"}},
            "data": "owner:clients:page:1",
        },
    }
    await router.process_update(cb_list, db_session)
    assert "client_alpha" in mock_client.edited_messages[0]["text"]

    # 4. Owner opens Client Detail -> owner:client:view:<id>
    cb_detail = {
        "update_id": 3,
        "callback_query": {
            "id": "cq_2",
            "from": {"id": 100, "username": "boss"},
            "message": {"message_id": 10, "chat": {"id": 100, "type": "private"}},
            "data": f"owner:client:view:{client_a.id}",
        },
    }
    await router.process_update(cb_detail, db_session)
    assert "Client Details" in mock_client.edited_messages[1]["text"]

    # 5. Owner clicks Suspend -> owner:client:suspend:<id> -> prompts confirmation
    cb_susp = {
        "update_id": 4,
        "callback_query": {
            "id": "cq_3",
            "from": {"id": 100, "username": "boss"},
            "message": {"message_id": 10, "chat": {"id": 100, "type": "private"}},
            "data": f"owner:client:suspend:{client_a.id}",
        },
    }
    await router.process_update(cb_susp, db_session)
    assert "Suspend @client_alpha?" in mock_client.edited_messages[2]["text"]

    # 6. Owner confirms Suspend -> owner:client:suspend_confirm:<id>
    cb_susp_confirm = {
        "update_id": 5,
        "callback_query": {
            "id": "cq_4",
            "from": {"id": 100, "username": "boss"},
            "message": {"message_id": 10, "chat": {"id": 100, "type": "private"}},
            "data": f"owner:client:suspend_confirm:{client_a.id}",
        },
    }
    await router.process_update(cb_susp_confirm, db_session)
    await db_session.commit()
    assert "suspended" in mock_client.edited_messages[3]["text"].lower()

    # 7. Verify Client Alpha is blocked when sending /start
    client_start = {
        "update_id": 6,
        "message": {
            "message_id": 20,
            "chat": {"id": 200, "type": "private"},
            "from": {"id": 200, "username": "client_alpha"},
            "text": "/start",
        },
    }
    res_client = await router.process_update(client_start, db_session)
    assert res_client["action"] == "client_suspended"
    assert "temporarily suspended" in mock_client.sent_messages[1]["text"]

    # 8. Owner reactivates Client Alpha -> owner:client:reactivate_confirm:<id>
    cb_reactivate = {
        "update_id": 7,
        "callback_query": {
            "id": "cq_5",
            "from": {"id": 100, "username": "boss"},
            "message": {"message_id": 10, "chat": {"id": 100, "type": "private"}},
            "data": f"owner:client:reactivate_confirm:{client_a.id}",
        },
    }
    await router.process_update(cb_reactivate, db_session)
    await db_session.commit()
    assert "reactivated" in mock_client.edited_messages[4]["text"].lower()

    # 9. Client Alpha /start works again
    res_client2 = await router.process_update(client_start, db_session)
    assert res_client2["action"] in ("new_client_welcome", "client_home")


@pytest.mark.asyncio
async def test_owner_jobs_and_retry_flow(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    # Setup Owner and a failed Job
    owner = PlatformOwner(telegram_user_id=100, username="boss", is_active=True)
    db_session.add(owner)
    job_repo = BackgroundJobRepository(db_session)
    job = await job_repo.create_job(
        job_type=JobType.VIDEO_PROCESS,
        payload={"vid": 1},
        max_attempts=1,
    )

    await job_repo.mark_running(job.id)
    await job_repo.mark_failed(job.id, "ERR_FAIL", "Extraction failed")
    await db_session.commit()

    # 1. Owner opens /jobs
    cmd = {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "chat": {"id": 100, "type": "private"},
            "from": {"id": 100, "username": "boss"},
            "text": "/jobs",
        },
    }
    await router.process_update(cmd, db_session)
    assert "Background Jobs" in mock_client.sent_messages[0]["text"]

    # 2. View Failed Jobs
    cb_failed = {
        "update_id": 2,
        "callback_query": {
            "id": "cq_10",
            "from": {"id": 100, "username": "boss"},
            "message": {"message_id": 10, "chat": {"id": 100, "type": "private"}},
            "data": "owner:jobs:failed:1",
        },
    }
    await router.process_update(cb_failed, db_session)
    assert "Failed Jobs" in mock_client.edited_messages[0]["text"]

    # 3. View Job Detail
    cb_job_detail = {
        "update_id": 3,
        "callback_query": {
            "id": "cq_11",
            "from": {"id": 100, "username": "boss"},
            "message": {"message_id": 10, "chat": {"id": 100, "type": "private"}},
            "data": f"owner:job:view:{job.id}",
        },
    }
    await router.process_update(cb_job_detail, db_session)
    assert "Job Details" in mock_client.edited_messages[1]["text"]

    # 4. Confirm Retry
    cb_retry_confirm = {
        "update_id": 4,
        "callback_query": {
            "id": "cq_12",
            "from": {"id": 100, "username": "boss"},
            "message": {"message_id": 10, "chat": {"id": 100, "type": "private"}},
            "data": f"owner:job:retry_confirm:{job.id}",
        },
    }
    await router.process_update(cb_retry_confirm, db_session)
    await db_session.commit()
    assert "Retry queued successfully" in mock_client.edited_messages[2]["text"]


@pytest.mark.asyncio
async def test_owner_queue_broadcasts_and_systemstats(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    owner = PlatformOwner(telegram_user_id=100, username="boss", is_active=True)
    db_session.add(owner)
    await db_session.commit()

    # 1. /queue
    await router.process_update(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": 100, "type": "private"},
                "from": {"id": 100, "username": "boss"},
                "text": "/queue",
            },
        },
        db_session,
    )
    assert "Queue Status" in mock_client.sent_messages[0]["text"]

    # 2. /broadcasts
    await router.process_update(
        {
            "update_id": 2,
            "message": {
                "message_id": 2,
                "chat": {"id": 100, "type": "private"},
                "from": {"id": 100, "username": "boss"},
                "text": "/broadcasts",
            },
        },
        db_session,
    )
    assert "Broadcast Activity" in mock_client.sent_messages[1]["text"]

    # 3. /systemstats
    await router.process_update(
        {
            "update_id": 3,
            "message": {
                "message_id": 3,
                "chat": {"id": 100, "type": "private"},
                "from": {"id": 100, "username": "boss"},
                "text": "/systemstats",
            },
        },
        db_session,
    )
    assert "Control Hub Statistics" in mock_client.sent_messages[2]["text"]


@pytest.mark.asyncio
async def test_unauthorized_owner_callback_rejection(db_session: AsyncSession):
    mock_client = MockTelegramClient()
    router = ControlHubRouter(telegram_client=mock_client)

    # Non-owner user attempts to craft owner:client:suspend:1
    cb_hack = {
        "update_id": 1,
        "callback_query": {
            "id": "cq_999",
            "from": {"id": 999, "username": "evil_user"},
            "message": {"message_id": 50, "chat": {"id": 999, "type": "private"}},
            "data": "owner:client:suspend_confirm:1",
        },
    }
    res = await router.process_update(cb_hack, db_session)
    assert res["action"] == "unauthorized_callback"
    assert "Access Denied" in mock_client.edited_messages[0]["text"]
