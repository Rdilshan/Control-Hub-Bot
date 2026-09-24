"""Unit tests for PlatformOwnerService."""

from datetime import datetime, timezone
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
    BroadcastStatus,
    ClientBotStatus,
    ClientStatus,
    JobStatus,
    JobType,
)
from app.db.base import Base
from app.repositories.broadcast import BroadcastRepository
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository
from app.repositories.viewer import ViewerRepository
from app.services.platform_owner_service import PlatformOwnerService


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
async def test_client_summary_and_pagination(db_session: AsyncSession):
    service = PlatformOwnerService(db_session)
    client_repo = ClientRepository(db_session)

    # Create 25 clients
    for i in range(1, 26):
        c, _ = await client_repo.get_or_create(telegram_user_id=1000 + i, username=f"user_{i}")
        if i % 5 == 0:
            await client_repo.suspend(c.id)

    await db_session.commit()

    # 1. Summary
    summary = await service.get_client_summary()
    assert summary["total"] == 25
    assert summary["suspended"] == 5
    assert summary["active"] == 20
    assert summary["new_today"] == 25

    # 2. Pagination (Page 1)
    items_p1, total_count, total_pages = await service.list_clients(page=1, page_size=10)
    assert total_count == 25
    assert total_pages == 3
    assert len(items_p1) == 10

    # 3. Pagination (Page 3)
    items_p3, _, _ = await service.list_clients(page=3, page_size=10)
    assert len(items_p3) == 5


@pytest.mark.asyncio
async def test_client_search(db_session: AsyncSession):
    service = PlatformOwnerService(db_session)
    client_repo = ClientRepository(db_session)

    c1, _ = await client_repo.get_or_create(telegram_user_id=888111, username="movie_king")
    c2, _ = await client_repo.get_or_create(telegram_user_id=888222, username="series_queen")
    await db_session.commit()

    # Search by username substring
    res = await service.search_clients("movie")
    assert len(res) == 1
    assert res[0]["client"].username == "movie_king"

    # Search by numeric Telegram ID
    res2 = await service.search_clients("888222")
    assert len(res2) == 1
    assert res2[0]["client"].username == "series_queen"


@pytest.mark.asyncio
async def test_client_suspension_and_reactivation(db_session: AsyncSession):
    service = PlatformOwnerService(db_session)
    client_repo = ClientRepository(db_session)

    c, _ = await client_repo.get_or_create(telegram_user_id=555000, username="bad_actor")
    await db_session.commit()

    # 1. Suspend
    ok, msg, updated = await service.suspend_client(c.id, performed_by_owner_id=1)
    assert ok is True
    assert updated.status == ClientStatus.SUSPENDED

    # Duplicate suspend returns False
    ok_dup, _, _ = await service.suspend_client(c.id, performed_by_owner_id=1)
    assert ok_dup is False

    # 2. Reactivate
    ok_re, msg_re, reactivated = await service.reactivate_client(c.id, performed_by_owner_id=1)
    assert ok_re is True
    assert reactivated.status == ClientStatus.ACTIVE


@pytest.mark.asyncio
async def test_bot_summary_and_search(db_session: AsyncSession):
    service = PlatformOwnerService(db_session)
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)

    c, _ = await client_repo.get_or_create(telegram_user_id=4001, username="owner_c")
    b1 = await bot_repo.create_with_defaults(
        client_id=c.id, telegram_bot_id=11111, token="tok_1", username="AnimeBot"
    )
    b2 = await bot_repo.create_with_defaults(
        client_id=c.id, telegram_bot_id=22222, token="tok_2", username="CinemaBot"
    )
    await bot_repo.pause_bot(b2.id)
    await db_session.commit()

    summary = await service.get_bot_summary()
    assert summary["total"] == 2
    assert summary["active"] == 1
    assert summary["paused"] == 1

    # Search by username
    found = await service.search_bots("anime")
    assert len(found) == 1
    assert found[0]["bot"].username == "AnimeBot"


@pytest.mark.asyncio
async def test_job_summary_and_retry(db_session: AsyncSession):
    service = PlatformOwnerService(db_session)
    job_repo = BackgroundJobRepository(db_session)

    j1 = await job_repo.create_job(
        job_type=JobType.VIDEO_PROCESS,
        payload={"video_id": 10},
        max_attempts=3,
    )

    await job_repo.mark_running(j1.id)
    await job_repo.mark_failed(j1.id, "ERR_THUMB", "Thumbnail extraction failed")
    await job_repo.mark_running(j1.id)
    await job_repo.mark_failed(j1.id, "ERR_THUMB", "Thumbnail extraction failed")
    await job_repo.mark_running(j1.id)
    await job_repo.mark_failed(j1.id, "ERR_THUMB", "Thumbnail extraction failed")
    await db_session.commit()

    # Job is FAILED
    detail = await service.get_job_detail(j1.id)
    assert detail["job"].status == JobStatus.FAILED

    # Retry job
    ok, msg, retried_job = await service.retry_job(j1.id, performed_by_owner_id=1)
    assert ok is True
    assert retried_job.status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_system_stats_aggregate(db_session: AsyncSession):
    service = PlatformOwnerService(db_session)
    client_repo = ClientRepository(db_session)
    bot_repo = ClientBotRepository(db_session)
    viewer_repo = ViewerRepository(db_session)
    video_repo = VideoRepository(db_session)

    c, _ = await client_repo.get_or_create(telegram_user_id=7001)
    b = await bot_repo.create_with_defaults(client_id=c.id, telegram_bot_id=8001, token="tok_b")
    await viewer_repo.get_or_create_viewer(client_bot_id=b.id, telegram_user_id=9001)
    await video_repo.create_video(
        client_bot_id=b.id,
        telegram_file_id="file_123",
        telegram_file_unique_id="uniq_123",
    )
    await db_session.commit()

    stats = await service.get_system_stats()
    assert stats["total_clients"] == 1
    assert stats["total_bots"] == 1
    assert stats["total_viewers"] == 1
    assert stats["total_videos"] == 1
    assert stats["new_clients_today"] == 1
    assert stats["videos_created_today"] == 1
