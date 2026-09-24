"""Integration tests for all database models and repositories using async database session."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.exc import IntegrityError
from app.db.base import Base
from app.core.enums import (
    BotAdminRole,
    ClientBotStatus,
    ClientStatus,
    JobType,
    ViewerStatus,
    VideoStatus,
)
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.repositories.client_bot_admin import ClientBotAdminRepository
from app.repositories.client_bot_settings import ClientBotSettingsRepository
from app.repositories.sponsor import SponsorRepository
from app.repositories.viewer import ViewerRepository
from app.repositories.video import VideoRepository
from app.repositories.video_processing import VideoProcessingRepository
from app.repositories.unlock_link import UnlockLinkRepository
from app.repositories.broadcast import BroadcastRepository
from app.repositories.delivery import BroadcastDeliveryRepository
from app.repositories.catchup import CatchupDeliveryRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.platform_owner import PlatformOwnerRepository


@pytest_asyncio.fixture
async def db_session():
    """Sets up an in-memory SQLite database for testing models and repositories."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_platform_owner_repo(db_session: AsyncSession):
    repo = PlatformOwnerRepository(db_session)
    owner = await repo.create(telegram_user_id=111222, username="owner_user")
    assert owner.id is not None
    assert await repo.is_owner(111222) is True
    assert await repo.is_owner(999999) is False


@pytest.mark.asyncio
async def test_client_repo_unique_and_get_or_create(db_session: AsyncSession):
    repo = ClientRepository(db_session)
    client1, created1 = await repo.get_or_create(telegram_user_id=1001, username="client1")
    assert created1 is True
    assert client1.status == ClientStatus.ACTIVE

    # Second call returns existing client without duplicate
    client2, created2 = await repo.get_or_create(telegram_user_id=1001, username="client1_updated")
    assert created2 is False
    assert client2.id == client1.id
    assert client2.username == "client1_updated"


@pytest.mark.asyncio
async def test_client_bot_repo_and_multi_bot(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)

    client, _ = await client_repo.get_or_create(telegram_user_id=2001)

    # 1. Create Bot 1
    bot1 = await bot_repo.create_with_defaults(
        client_id=client.id,
        telegram_bot_id=888001,
        token="token_bot_1",
        username="movie_bot_1",
        owner_telegram_user_id=2001,
    )
    assert bot1.id is not None
    assert bot1.client_id == client.id

    # 2. Create Bot 2 for same client
    bot2 = await bot_repo.create_with_defaults(
        client_id=client.id,
        telegram_bot_id=888002,
        token="token_bot_2",
        username="movie_bot_2",
        owner_telegram_user_id=2001,
    )
    assert bot2.id is not None
    assert bot2.id != bot1.id

    # 3. List bots by client
    bots = await bot_repo.list_by_client(client.id)
    assert len(bots) == 2

    # 4. Decrypted token check
    assert await bot_repo.get_decrypted_token(bot1.id) == "token_bot_1"
    assert await bot_repo.get_decrypted_token(bot2.id) == "token_bot_2"


@pytest.mark.asyncio
async def test_duplicate_telegram_bot_id_rejected(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)

    c1, _ = await client_repo.get_or_create(telegram_user_id=3001)
    c2, _ = await client_repo.get_or_create(telegram_user_id=3002)

    await bot_repo.create_with_defaults(
        client_id=c1.id,
        telegram_bot_id=999111,
        token="token_1",
    )

    with pytest.raises(IntegrityError):
        await bot_repo.create_with_defaults(
            client_id=c2.id,
            telegram_bot_id=999111,  # Same Telegram bot ID must fail
            token="token_2",
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_bot_admin_roles_and_unique_constraint(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    admin_repo = ClientBotAdminRepository(db_session)

    c, _ = await client_repo.get_or_create(telegram_user_id=4001)
    bot = await bot_repo.create_with_defaults(
        client_id=c.id,
        telegram_bot_id=777001,
        token="tok_1",
        owner_telegram_user_id=4001,
    )

    # Automatically created owner admin
    assert await admin_repo.is_admin_or_owner(bot.id, 4001) is True
    assert await admin_repo.is_admin_or_owner(bot.id, 9999) is False

    # Add second admin
    await admin_repo.add_admin(
        client_bot_id=bot.id,
        telegram_user_id=4002,
        role=BotAdminRole.ADMIN,
    )
    assert await admin_repo.is_admin_or_owner(bot.id, 4002) is True

    # Duplicate admin per same bot rejected
    with pytest.raises(IntegrityError):
        await admin_repo.add_admin(
            client_bot_id=bot.id,
            telegram_user_id=4002,
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_bot_settings_and_sponsor(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    settings_repo = ClientBotSettingsRepository(db_session)
    sponsor_repo = SponsorRepository(db_session)

    c, _ = await client_repo.get_or_create(telegram_user_id=5001)
    bot = await bot_repo.create_with_defaults(client_id=c.id, telegram_bot_id=666001, token="tok")

    # Settings
    settings = await settings_repo.get_by_bot_id(bot.id)
    assert settings is not None
    await settings_repo.update_default_message(bot.id, "Custom default message")
    updated_settings = await settings_repo.get_by_bot_id(bot.id)
    assert updated_settings.default_message == "Custom default message"

    # Sponsor
    sponsor = await sponsor_repo.get_by_bot_id(bot.id)
    assert sponsor.is_enabled is False
    await sponsor_repo.update_sponsor(bot.id, sponsor_url="https://monetag.com/direct", is_enabled=True)
    updated_sponsor = await sponsor_repo.get_by_bot_id(bot.id)
    assert updated_sponsor.is_enabled is True
    assert updated_sponsor.sponsor_url == "https://monetag.com/direct"


@pytest.mark.asyncio
async def test_viewer_multi_bot_and_duplicate_prevention(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    viewer_repo = ViewerRepository(db_session)

    c, _ = await client_repo.get_or_create(telegram_user_id=6001)
    bot1 = await bot_repo.create_with_defaults(client_id=c.id, telegram_bot_id=555001, token="tok1")
    bot2 = await bot_repo.create_with_defaults(client_id=c.id, telegram_bot_id=555002, token="tok2")

    # Same Telegram viewer in Bot 1 and Bot 2
    v1, is_new1 = await viewer_repo.get_or_create_viewer(
        client_bot_id=bot1.id,
        telegram_user_id=777888,
        username="viewer_user",
    )
    v2, is_new2 = await viewer_repo.get_or_create_viewer(
        client_bot_id=bot2.id,
        telegram_user_id=777888,
        username="viewer_user",
    )
    assert is_new1 is True
    assert is_new2 is True
    assert v1.id != v2.id
    assert v1.client_bot_id == bot1.id
    assert v2.client_bot_id == bot2.id

    # Duplicate call in Bot 1 reuses existing
    v1_existing, is_new1_dup = await viewer_repo.get_or_create_viewer(
        client_bot_id=bot1.id,
        telegram_user_id=777888,
    )
    assert is_new1_dup is False
    assert v1_existing.id == v1.id


@pytest.mark.asyncio
async def test_video_creation_and_processing(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    video_repo = VideoRepository(db_session)
    proc_repo = VideoProcessingRepository(db_session)
    unlock_repo = UnlockLinkRepository(db_session)

    c, _ = await client_repo.get_or_create(telegram_user_id=7001)
    bot = await bot_repo.create_with_defaults(client_id=c.id, telegram_bot_id=444001, token="tok")

    video = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="BAADBAADAgAD...",
        telegram_file_unique_id="unique_file_123",
        caption="Fast Action Movie",
    )
    assert video.id is not None
    assert video.status == VideoStatus.RECEIVED

    # Check processing record was created automatically
    proc = await proc_repo.get_by_video_id(video.id)
    assert proc is not None

    # Unlock link
    link = await unlock_repo.create(video_id=video.id, client_bot_id=bot.id, url="https://unlockify.it/xyz")
    assert link.id is not None

    # Mark ready
    ready_vid = await video_repo.mark_ready(video.id, bot.id)
    assert ready_vid.status == VideoStatus.READY
    assert ready_vid.published_at is not None


@pytest.mark.asyncio
async def test_broadcast_and_duplicate_delivery(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    video_repo = VideoRepository(db_session)
    viewer_repo = ViewerRepository(db_session)
    bcast_repo = BroadcastRepository(db_session)
    delivery_repo = BroadcastDeliveryRepository(db_session)

    c, _ = await client_repo.get_or_create(telegram_user_id=8001)
    bot = await bot_repo.create_with_defaults(client_id=c.id, telegram_bot_id=333001, token="tok")
    video = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="file_id",
        telegram_file_unique_id="uniq_1",
    )
    viewer, _ = await viewer_repo.get_or_create_viewer(client_bot_id=bot.id, telegram_user_id=9001)

    broadcast = await bcast_repo.create_broadcast(
        client_bot_id=bot.id,
        video_id=video.id,
        total_targets=1,
    )
    assert broadcast.id is not None

    delivery = await delivery_repo.create_pending_delivery(
        broadcast_id=broadcast.id,
        viewer_id=viewer.id,
    )
    assert delivery.id is not None

    # Duplicate delivery for same broadcast/viewer must fail
    with pytest.raises(IntegrityError):
        await delivery_repo.create_pending_delivery(
            broadcast_id=broadcast.id,
            viewer_id=viewer.id,
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_catchup_delivery_duplicate_prevention(db_session: AsyncSession):
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    video_repo = VideoRepository(db_session)
    viewer_repo = ViewerRepository(db_session)
    catchup_repo = CatchupDeliveryRepository(db_session)

    c, _ = await client_repo.get_or_create(telegram_user_id=9001)
    bot = await bot_repo.create_with_defaults(client_id=c.id, telegram_bot_id=222001, token="tok")
    video = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="file_id",
        telegram_file_unique_id="uniq_2",
    )
    viewer, _ = await viewer_repo.get_or_create_viewer(client_bot_id=bot.id, telegram_user_id=9002)

    assert await catchup_repo.has_received_video(viewer.id, video.id) is False

    await catchup_repo.record_catchup_sent(client_bot_id=bot.id, viewer_id=viewer.id, video_id=video.id)
    assert await catchup_repo.has_received_video(viewer.id, video.id) is True

    delivered_ids = await catchup_repo.list_delivered_video_ids_for_viewer(viewer.id)
    assert video.id in delivered_ids


@pytest.mark.asyncio
async def test_background_jobs_repo(db_session: AsyncSession):
    job_repo = BackgroundJobRepository(db_session)
    job = await job_repo.create_job(
        job_type=JobType.VIDEO_PROCESS,
        payload={"video_id": 123},
    )
    assert job.id is not None
    assert job.status == "PENDING"

    running = await job_repo.mark_running(job.id)
    assert running.status == "RUNNING"
    assert running.attempt_count == 1

    completed = await job_repo.mark_completed(job.id)
    assert completed.status == "COMPLETED"
