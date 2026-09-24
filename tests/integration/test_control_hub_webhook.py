"""Integration tests for Control Hub Webhook endpoint."""

from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app


@pytest_asyncio.fixture
async def webhook_test_app(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "super_secret_webhook_token_123")
    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_webhook_missing_secret_rejected(webhook_test_app: AsyncClient):
    payload = {
        "update_id": 1,
        "message": {"message_id": 1, "chat": {"id": 123}, "text": "/start"},
    }
    response = await webhook_test_app.post(
        "/api/v1/webhooks/telegram/control-hub",
        json=payload,
    )
    assert response.status_code == 403
    assert "Invalid Telegram webhook secret token" in response.json()["error"]["message"]



@pytest.mark.asyncio
async def test_webhook_wrong_secret_rejected(webhook_test_app: AsyncClient):
    payload = {
        "update_id": 2,
        "message": {"message_id": 2, "chat": {"id": 123}, "text": "/start"},
    }
    response = await webhook_test_app.post(
        "/api/v1/webhooks/telegram/control-hub",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webhook_valid_secret_processed(webhook_test_app: AsyncClient):
    payload = {
        "update_id": 3,
        "message": {
            "message_id": 3,
            "chat": {"id": 999, "type": "private"},
            "from": {"id": 999, "username": "alice"},
            "text": "/start",
        },
    }

    with patch("app.telegram.control_hub.router.TelegramClient.send_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True}

        response = await webhook_test_app.post(
            "/api/v1/webhooks/telegram/control-hub",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "super_secret_webhook_token_123"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert mock_send.called
