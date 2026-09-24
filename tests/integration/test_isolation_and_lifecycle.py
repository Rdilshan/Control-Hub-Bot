"""Tests for cross-bot data isolation and bot lifecycle data preservation."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.db.base import Base
from app.core.enums import ClientBotStatus
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.repositories.video import VideoRepository
from app.repositories.viewer import ViewerRepository


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
async def test_cross_bot_video_isolation(db_session: AsyncSession):
    """Verifies that Client A / Bot A cannot access Video B belonging to Bot B."""
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    video_repo = VideoRepository(db_session)

    # Client A and Bot A
    client_a, _ = await client_repo.get_or_create(telegram_user_id=101)
    bot_a = await bot_repo.create_with_defaults(client_id=client_a.id, telegram_bot_id=1010, token="tok_a")
    video_a = await video_repo.create_video(
        client_bot_id=bot_a.id,
        telegram_file_id="file_a",
        telegram_file_unique_id="uniq_a",
    )

    # Client B and Bot B
    client_b, _ = await client_repo.get_or_create(telegram_user_id=202)
    bot_b = await bot_repo.create_with_defaults(client_id=client_b.id, telegram_bot_id=2020, token="tok_b")
    video_b = await video_repo.create_video(
        client_bot_id=bot_b.id,
        telegram_file_id="file_b",
        telegram_file_unique_id="uniq_b",
    )

    # Querying Video B with Bot A's ID must return None (isolation protected)
    isolated_result = await video_repo.get_by_id_and_bot(
        video_id=video_b.id,
        client_bot_id=bot_a.id,
    )
    assert isolated_result is None

    # Querying Video A with Bot A's ID succeeds
    valid_result = await video_repo.get_by_id_and_bot(
        video_id=video_a.id,
        client_bot_id=bot_a.id,
    )
    assert valid_result is not None
    assert valid_result.id == video_a.id


@pytest.mark.asyncio
async def test_bot_pause_resume_disconnect_lifecycle(db_session: AsyncSession):
    """Verifies pause, resume, and disconnect preserve all viewers, videos, and settings."""
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    video_repo = VideoRepository(db_session)
    viewer_repo = ViewerRepository(db_session)

    client, _ = await client_repo.get_or_create(telegram_user_id=303)
    bot = await bot_repo.create_with_defaults(client_id=client.id, telegram_bot_id=3030, token="secret_tok")

    # Add viewer and video
    await viewer_repo.get_or_create_viewer(client_bot_id=bot.id, telegram_user_id=404)
    video = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="file_303",
        telegram_file_unique_id="uniq_303",
    )

    # 1. Pause Bot
    paused_bot = await bot_repo.pause_bot(bot.id)
    assert paused_bot.status == ClientBotStatus.PAUSED
    assert paused_bot.paused_at is not None

    # Confirm viewers and videos are preserved
    assert await viewer_repo.count_by_bot(bot.id) == 1
    assert await video_repo.count_by_bot(bot.id) == 1

    # 2. Resume Bot
    resumed_bot = await bot_repo.resume_bot(bot.id)
    assert resumed_bot.status == ClientBotStatus.ACTIVE
    assert resumed_bot.paused_at is None

    # 3. Disconnect Bot
    disconnected_bot = await bot_repo.disconnect_bot(bot.id)
    assert disconnected_bot.status == ClientBotStatus.DISCONNECTED
    assert disconnected_bot.disconnected_at is not None
    assert disconnected_bot.token_encrypted is None  # Token revoked on disconnect

    # Confirm history is still fully preserved
    assert await viewer_repo.count_by_bot(bot.id) == 1
    assert await video_repo.count_by_bot(bot.id) == 1
    found_video = await video_repo.get_by_id_and_bot(video.id, bot.id)
    assert found_video is not None
