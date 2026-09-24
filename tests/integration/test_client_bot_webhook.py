"""Integration tests for the Client Bot dynamic webhook endpoint."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import BotAdminRole, ClientBotStatus
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.client_bot_settings import ClientBotSettings
from app.db.session import get_db
from app.main import create_app


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
async def client_bot_app_client(db_session: AsyncSession):
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_client_bot_webhook_not_found(client_bot_app_client: AsyncClient):
    """Verifies that requests to non-existent public_bot_ids return 404."""
    response = await client_bot_app_client.post(
        "/api/v1/webhooks/telegram/client/b_nonexistent99",
        json={"update_id": 1, "message": {"text": "/start"}},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_client_bot_webhook_secret_token_validation(
    db_session: AsyncSession,
    client_bot_app_client: AsyncClient,
):
    """Verifies secret token verification for client bots."""
    # Setup client and bot with secret
    secret = "SuperSecretToken_12345"
    client = Client(telegram_user_id=12301, username="test_client")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=888101,
        username="SecretBot",
        token_encrypted=encrypt_token("888101:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"),
        webhook_secret_encrypted=encrypt_token(secret),
        public_id="b_secretbot12",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.commit()

    # 1. Missing secret token -> 403 Forbidden
    res_no_secret = await client_bot_app_client.post(
        "/api/v1/webhooks/telegram/client/b_secretbot12",
        json={"update_id": 1, "message": {"text": "/start"}},
    )
    assert res_no_secret.status_code == 403
    assert res_no_secret.json()["error"]["code"] == "FORBIDDEN"

    # 2. Wrong secret token -> 403 Forbidden
    res_wrong_secret = await client_bot_app_client.post(
        "/api/v1/webhooks/telegram/client/b_secretbot12",
        headers={"X-Telegram-Bot-Api-Secret-Token": "WrongSecret"},
        json={"update_id": 2, "message": {"text": "/start"}},
    )
    assert res_wrong_secret.status_code == 403
    assert res_wrong_secret.json()["error"]["code"] == "FORBIDDEN"

    # 3. Valid secret token -> 200 OK
    with patch("app.telegram.client.TelegramClient.send_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"message_id": 10}
        res_valid = await client_bot_app_client.post(
            "/api/v1/webhooks/telegram/client/b_secretbot12",
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            json={
                "update_id": 3,
                "message": {
                    "message_id": 1,
                    "chat": {"id": 99901, "type": "private"},
                    "from": {"id": 99901, "username": "viewer", "first_name": "Viewer"},
                    "text": "/start",
                },
            },
        )
        assert res_valid.status_code == 200
        data = res_valid.json()
        assert data["ok"] is True
        assert data["result"]["action"] == "viewer_start"
