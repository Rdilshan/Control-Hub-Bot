"""Unit tests for ClientBotConnectionService."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import ClientBotStatus, ClientStatus, enum_val
from app.db.base import Base
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.services.client_bot_connection_service import ClientBotConnectionService
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
async def test_token_format_and_validation(db_session: AsyncSession):
    service = ClientBotConnectionService(db_session)

    # 1. Invalid regex formats
    is_valid, info, err, is_net = await service.validate_token("invalid_token")
    assert is_valid is False
    assert "format" in err.lower()
    assert is_net is False

    is_valid, info, err, is_net = await service.validate_token("123:short")
    assert is_valid is False

    # 2. Mock valid getMe
    valid_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"
    with patch("app.telegram.client.TelegramClient.get_me", new_callable=AsyncMock) as mock_get_me:
        mock_get_me.return_value = TelegramBotInfo(
            id=123456789,
            is_bot=True,
            first_name="Movie Bot",
            username="MovieWorldBot",
        )
        is_valid, bot_info, err, is_net = await service.validate_token(valid_token)
        assert is_valid is True
        assert bot_info.username == "MovieWorldBot"
        assert bot_info.id == 123456789
        assert err is None


@pytest.mark.asyncio
async def test_check_bot_ownership_scenarios(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    service = ClientBotConnectionService(db_session)

    # Setup clients
    client_a, _ = await client_repo.get_or_create(telegram_user_id=1001, username="alice")
    client_b, _ = await client_repo.get_or_create(telegram_user_id=1002, username="bob")

    # 1. Case A: NEW bot
    status, bot = await service.check_bot_ownership(telegram_bot_id=999001, client_id=client_a.id)
    assert status == "NEW"
    assert bot is None

    # Create active bot for Client A
    created_bot = await bot_repo.create_with_defaults(
        client_id=client_a.id,
        telegram_bot_id=999001,
        token="123456:ABCdefGHIjklMNOpqrsTUVwxyz_1234567",
        username="AliceBot",
    )
    created_bot.status = ClientBotStatus.ACTIVE
    await db_session.flush()

    # 2. Case B: ALREADY_CONNECTED by same client
    status, bot = await service.check_bot_ownership(telegram_bot_id=999001, client_id=client_a.id)
    assert status == "ALREADY_CONNECTED"
    assert bot is not None
    assert bot.id == created_bot.id

    # 3. Case C: OTHER_OWNER by Client B
    status, bot = await service.check_bot_ownership(telegram_bot_id=999001, client_id=client_b.id)
    assert status == "OTHER_OWNER"
    assert bot is None

    # 4. Case D: RECONNECT when status is DISCONNECTED
    created_bot.status = ClientBotStatus.DISCONNECTED
    await db_session.flush()

    status, bot = await service.check_bot_ownership(telegram_bot_id=999001, client_id=client_a.id)
    assert status == "RECONNECT"
    assert bot is not None
    assert bot.id == created_bot.id


@pytest.mark.asyncio
async def test_pending_connection_lifecycle_and_confirmation(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    service = ClientBotConnectionService(db_session)

    client, _ = await client_repo.get_or_create(telegram_user_id=2001, username="charlie")
    bot_info = TelegramBotInfo(
        id=777888999,
        is_bot=True,
        first_name="Charlie Bot",
        username="CharlieBot",
    )
    token = "777888999:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"

    # Prepare pending
    temp_id = await service.prepare_pending_connection(
        client_id=client.id,
        raw_token=token,
        bot_info=bot_info,
    )
    assert temp_id is not None

    pending = await service.get_pending_connection(temp_id)
    assert pending["client_id"] == client.id
    assert pending["telegram_bot_id"] == 777888999
    assert pending["username"] == "CharlieBot"

    # Mock provisioning to succeed
    with patch("app.services.client_bot_provisioning_service.ClientBotProvisioningService.provision_bot", new_callable=AsyncMock) as mock_prov:
        mock_prov.return_value = (True, "Bot provisioned successfully")

        success, msg, connected_bot = await service.confirm_connection(
            client_id=client.id,
            temp_id=temp_id,
        )

        assert success is True
        assert connected_bot is not None
        assert connected_bot.telegram_bot_id == 777888999
        assert connected_bot.username == "CharlieBot"
        assert connected_bot.client_id == client.id

    # Pending session should now be cleared
    cleared = await service.get_pending_connection(temp_id)
    assert cleared is None
