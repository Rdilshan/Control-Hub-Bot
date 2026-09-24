"""Unit tests for ClientOnboardingService."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import ClientBotStatus, ClientStatus
from app.db.base import Base
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.services.client_onboarding_service import ClientOnboardingService


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
async def test_resolve_or_create_client_and_sync_profile(db_session: AsyncSession):
    service = ClientOnboardingService(db_session)

    # 1. New client
    client, is_new = await service.resolve_or_create_client(
        telegram_user_id=12345,
        username="old_handle",
        first_name="Alice",
    )
    assert is_new is True
    assert client.telegram_user_id == 12345
    assert client.username == "old_handle"
    assert client.status == ClientStatus.ACTIVE

    # 2. Returning client with updated username
    client2, is_new2 = await service.resolve_or_create_client(
        telegram_user_id=12345,
        username="new_handle",
        first_name="Alice B",
    )
    assert is_new2 is False
    assert client2.id == client.id
    assert client2.username == "new_handle"
    assert client2.first_name == "Alice B"


@pytest.mark.asyncio
async def test_client_bot_multi_tenant_isolation(db_session: AsyncSession):
    service = ClientOnboardingService(db_session)
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)

    c1, _ = await client_repo.get_or_create(telegram_user_id=101)
    c2, _ = await client_repo.get_or_create(telegram_user_id=102)

    b1 = await bot_repo.create_with_defaults(client_id=c1.id, telegram_bot_id=1001, token="tok_1")
    b2 = await bot_repo.create_with_defaults(client_id=c2.id, telegram_bot_id=1002, token="tok_2")
    await db_session.commit()

    # C1 bots
    c1_bots = await service.list_client_bots(c1.id)
    assert len(c1_bots) == 1
    assert c1_bots[0].id == b1.id

    # C1 attempts to access B2 belonging to C2 -> returns None
    b2_for_c1 = await service.get_bot_for_client(bot_id=b2.id, client_id=c1.id)
    assert b2_for_c1 is None

    # C2 accesses B2 -> returns detail dict
    b2_for_c2 = await service.get_bot_for_client(bot_id=b2.id, client_id=c2.id)
    assert b2_for_c2 is not None
    assert b2_for_c2["bot"].id == b2.id


@pytest.mark.asyncio
async def test_client_account_summary(db_session: AsyncSession):
    service = ClientOnboardingService(db_session)
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)

    c, _ = await client_repo.get_or_create(telegram_user_id=301, username="pro_user")
    await bot_repo.create_with_defaults(client_id=c.id, telegram_bot_id=5001, token="tok_1")
    await bot_repo.create_with_defaults(client_id=c.id, telegram_bot_id=5002, token="tok_2")
    await db_session.commit()

    summary = await service.get_client_account_summary(c.id)
    assert summary["username"] == "pro_user"
    assert summary["total_bots"] == 2
    assert summary["status"] == "ACTIVE"
