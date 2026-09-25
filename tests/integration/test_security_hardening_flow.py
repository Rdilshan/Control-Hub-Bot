"""Integration tests for security hardening, tenant boundaries, and webhook protection."""

import pytest
from httpx import AsyncClient, ASGITransport
from app.core.enums import BotStatus
from app.exceptions import ForbiddenError, NotFoundError
from app.main import create_app
from app.security.authorization import AuthorizationService
from app.security.tenant_guard import TenantGuardService
from app.security.token_encryption import BotTokenEncryptionService
from app.security.webhook_security import WebhookSecurityService


class DummyBot:
    def __init__(self, id=1, client_id=10, status=BotStatus.ACTIVE, token_encrypted="encrypted_token_123"):
        self.id = id
        self.client_id = client_id
        self.status = status
        self.token_encrypted = token_encrypted
        self.webhook_secret_encrypted = "encrypted_secret_456"


class DummyVideo:
    def __init__(self, id=55, client_bot_id=1):
        self.id = id
        self.client_bot_id = client_bot_id


def test_cross_bot_unlock_isolation():
    """Verifies that a video registered under Bot A cannot be accessed/unlocked through Bot B."""
    video_bot_a = DummyVideo(id=55, client_bot_id=1)
    
    # Valid access via Bot A (bot_id=1)
    TenantGuardService.assert_video_belongs_to_bot(video_bot_a, client_bot_id=1)

    # Attack: User in Bot B (bot_id=2) tries to access Bot A video
    with pytest.raises(ForbiddenError):
        TenantGuardService.assert_video_belongs_to_bot(video_bot_a, client_bot_id=2)


def test_cross_client_bot_access_isolation():
    """Verifies that Client A cannot operate on Client B's bot."""
    bot_client_1 = DummyBot(id=1, client_id=10)

    # Valid access by Client 10
    TenantGuardService.assert_bot_belongs_to_client(bot_client_1, client_id=10)

    # Attack: Client 20 tries to modify or access Client 10's bot
    with pytest.raises(ForbiddenError):
        TenantGuardService.assert_bot_belongs_to_client(bot_client_1, client_id=20)


def test_token_clearing_on_disconnect():
    """Verifies that active bot token is wiped clean from memory/model on disconnect."""
    encryption_service = BotTokenEncryptionService()
    bot = DummyBot(id=1, client_id=10)

    assert bot.token_encrypted is not None
    assert bot.webhook_secret_encrypted is not None

    encryption_service.clear_token_on_disconnect(bot)

    assert bot.token_encrypted is None
    assert bot.webhook_secret_encrypted is None


@pytest.mark.asyncio
async def test_webhook_secret_enforcement_and_not_found(monkeypatch):
    """Verifies FastAPI webhook endpoints return 404 for unknown bots and 403 for forged secrets."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.db.base import Base
    from app.db.session import get_db

    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "super_secret_hub_token")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Unknown public bot ID -> 404
        resp = await client.post(
            "/api/v1/webhooks/telegram/client/non_existent_public_id_999",
            json={"update_id": 1, "message": {"text": "/start"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "some_token"},
        )
        assert resp.status_code == 404

        # 2. Control Hub Webhook with invalid secret
        resp_ch = await client.post(
            "/api/v1/webhooks/telegram/control-hub",
            json={"update_id": 2, "message": {"text": "/start"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "invalid_hub_secret"},
        )
        assert resp_ch.status_code == 403

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

