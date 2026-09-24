"""Unit tests for ClientBotProvisioningService."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import BotAdminRole, ClientBotStatus, enum_val
from app.db.base import Base
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.services.client_bot_provisioning_service import ClientBotProvisioningService
from app.telegram.errors import TelegramNetworkError
from app.telegram.types import TelegramBotInfo


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_provisioning_success_flow(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    service = ClientBotProvisioningService(db_session)

    client, _ = await client_repo.get_or_create(telegram_user_id=3001, username="david")
    bot = await bot_repo.create_with_defaults(
        client_id=client.id,
        telegram_bot_id=888111,
        token="888111:ABCdefGHIjklMNOpqrsTUVwxyz_1234567",
        username="DavidBot",
        owner_telegram_user_id=client.telegram_user_id,
        owner_username=client.username,
    )
    bot.status = ClientBotStatus.PROVISIONING
    await db_session.flush()

    with patch("app.telegram.client.TelegramClient.get_me", new_callable=AsyncMock) as mock_get_me, \
         patch("app.telegram.client.TelegramClient.set_webhook", new_callable=AsyncMock) as mock_webhook, \
         patch("app.telegram.client.TelegramClient.set_my_commands", new_callable=AsyncMock) as mock_cmds:

        mock_get_me.return_value = TelegramBotInfo(
            id=888111,
            is_bot=True,
            first_name="David Bot",
            username="DavidBot",
        )
        mock_webhook.return_value = True
        mock_cmds.return_value = True

        success, msg = await service.provision_bot(client_bot_id=bot.id, client_id=client.id)

        assert success is True
        assert enum_val(bot.status) == "ACTIVE"
        assert bot.public_id is not None
        assert bot.webhook_secret_encrypted is not None

        # Verify webhook called with secret
        mock_webhook.assert_called_once()
        assert mock_cmds.call_count == 2  # default commands + owner commands


@pytest.mark.asyncio
async def test_provisioning_network_failure(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    service = ClientBotProvisioningService(db_session)

    client, _ = await client_repo.get_or_create(telegram_user_id=3002, username="emma")
    bot = await bot_repo.create_with_defaults(
        client_id=client.id,
        telegram_bot_id=888222,
        token="888222:ABCdefGHIjklMNOpqrsTUVwxyz_1234567",
        username="EmmaBot",
        owner_telegram_user_id=client.telegram_user_id,
    )
    bot.status = ClientBotStatus.PROVISIONING
    await db_session.flush()

    with patch("app.telegram.client.TelegramClient.get_me", new_callable=AsyncMock) as mock_get_me:
        mock_get_me.side_effect = TelegramNetworkError("Timeout reaching Telegram")

        success, msg = await service.provision_bot(client_bot_id=bot.id, client_id=client.id)

        assert success is False
        assert enum_val(bot.status) == "PROVISION_FAILED"
        assert "unreachable" in msg.lower()


@pytest.mark.asyncio
async def test_disconnect_bot_flow(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    service = ClientBotProvisioningService(db_session)

    client, _ = await client_repo.get_or_create(telegram_user_id=3003, username="frank")
    bot = await bot_repo.create_with_defaults(
        client_id=client.id,
        telegram_bot_id=888333,
        token="888333:ABCdefGHIjklMNOpqrsTUVwxyz_1234567",
        username="FrankBot",
        owner_telegram_user_id=client.telegram_user_id,
    )
    bot.status = ClientBotStatus.ACTIVE
    await db_session.flush()

    with patch("app.telegram.client.TelegramClient.delete_webhook", new_callable=AsyncMock) as mock_del_webhook:
        mock_del_webhook.return_value = True

        success, msg = await service.disconnect_bot(client_bot_id=bot.id, client_id=client.id)

        assert success is True
        assert enum_val(bot.status) == "DISCONNECTED"
        assert bot.disconnected_at is not None
        assert bot.token_encrypted is None
        mock_del_webhook.assert_called_once()
