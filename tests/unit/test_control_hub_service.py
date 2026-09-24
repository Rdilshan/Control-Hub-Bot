"""Unit tests for Control Hub Service role resolution and stats."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import ClientBotStatus, ControlHubRole
from app.db.base import Base
from app.db.models.platform_owner import PlatformOwner
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.services.control_hub_service import ControlHubService


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
async def test_role_resolution_precedence(db_session: AsyncSession):
    service = ControlHubService(db_session)

    # 1. Unknown user -> NEW_CLIENT
    role = await service.resolve_role(999999)
    assert role == ControlHubRole.NEW_CLIENT

    # 2. Add client record -> CLIENT
    client_repo = ClientRepository(db_session)
    client, _ = await client_repo.get_or_create(telegram_user_id=1001, username="testclient")
    await db_session.commit()

    role = await service.resolve_role(1001)
    assert role == ControlHubRole.CLIENT

    # 3. Add to platform_owners -> PLATFORM_OWNER takes priority
    owner = PlatformOwner(
        telegram_user_id=1001,
        username="owneruser",
        is_active=True,
    )
    db_session.add(owner)
    await db_session.commit()

    role = await service.resolve_role(1001)
    assert role == ControlHubRole.PLATFORM_OWNER

    # 4. Inactive platform owner falls back to client role
    owner.is_active = False
    await db_session.commit()

    role = await service.resolve_role(1001)
    assert role == ControlHubRole.CLIENT


@pytest.mark.asyncio
async def test_get_or_create_client(db_session: AsyncSession):
    service = ControlHubService(db_session)

    client1, is_new1 = await service.get_or_create_client(
        telegram_user_id=2001,
        username="john_doe",
        first_name="John",
    )
    assert is_new1 is True
    assert client1.telegram_user_id == 2001
    assert client1.username == "john_doe"

    # Fetch again
    client2, is_new2 = await service.get_or_create_client(
        telegram_user_id=2001,
        username="john_doe_updated",
    )
    assert is_new2 is False
    assert client2.id == client1.id
    assert client2.username == "john_doe_updated"


@pytest.mark.asyncio
async def test_owner_system_stats(db_session: AsyncSession):
    service = ControlHubService(db_session)
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)

    # Create 2 clients and 3 bots
    c1, _ = await client_repo.get_or_create(telegram_user_id=3001)
    c2, _ = await client_repo.get_or_create(telegram_user_id=3002)

    b1 = await bot_repo.create_with_defaults(client_id=c1.id, telegram_bot_id=5001, token="tok_1")
    b2 = await bot_repo.create_with_defaults(client_id=c1.id, telegram_bot_id=5002, token="tok_2")
    b3 = await bot_repo.create_with_defaults(client_id=c2.id, telegram_bot_id=5003, token="tok_3")
    await bot_repo.pause_bot(b3.id)
    await db_session.commit()


    stats = await service.get_owner_system_stats()
    assert stats["total_clients"] == 2
    assert stats["total_bots"] == 3
    assert stats["active_bots"] == 2
    assert stats["paused_bots"] == 1
    assert stats["disconnected_bots"] == 0
