"""Integration tests for Multi-Bot Management and Strict Cross-Bot Isolation:
One Client owning multiple bots with independent viewers, videos, sponsors, messages, and lifecycle states.
"""

from unittest.mock import AsyncMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
    BotAdminRole,
    ClientBotStatus,
    ClientStatus,
    VideoStatus,
    ViewerStatus,
)
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.client_bot_settings import ClientBotSettings
from app.db.models.sponsor_config import SponsorConfig
from app.db.models.video import Video
from app.db.models.viewer import Viewer
from app.repositories.video import VideoRepository
from app.repositories.viewer import ViewerRepository
from app.services.client_bot_lifecycle_service import ClientBotLifecycleService
from app.services.client_bot_management_service import ClientBotManagementService
from app.services.viewer_service import ViewerService
from app.services.viewer_unlock_service import ViewerUnlockService
from app.telegram.client import TelegramClient


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_full_multi_bot_isolation_journey(db_session: AsyncSession):
    # 1. Setup Client A (owns 3 bots) and Client B (owns 1 bot)
    client_a = Client(telegram_user_id=10101, username="owner_alice", status=ClientStatus.ACTIVE)
    client_b = Client(telegram_user_id=20202, username="owner_bob", status=ClientStatus.ACTIVE)
    db_session.add_all([client_a, client_b])
    await db_session.flush()

    # Create 3 bots for Client A
    bot_movie = ClientBot(
        client_id=client_a.id,
        telegram_bot_id=1001,
        username="MovieWorldBot",
        display_name="Movie World Bot",
        token_encrypted=encrypt_token("token_movie"),
        status=ClientBotStatus.ACTIVE,
    )
    bot_series = ClientBot(
        client_id=client_a.id,
        telegram_bot_id=1002,
        username="SeriesHubBot",
        display_name="Series Hub Bot",
        token_encrypted=encrypt_token("token_series"),
        status=ClientBotStatus.ACTIVE,
    )
    bot_anime = ClientBot(
        client_id=client_a.id,
        telegram_bot_id=1003,
        username="AnimeZoneBot",
        display_name="Anime Zone Bot",
        token_encrypted=encrypt_token("token_anime"),
        status=ClientBotStatus.ACTIVE,
    )

    # Create 1 bot for Client B
    bot_bob = ClientBot(
        client_id=client_b.id,
        telegram_bot_id=2001,
        username="BobsNewsBot",
        display_name="Bob's News Bot",
        token_encrypted=encrypt_token("token_bob"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add_all([bot_movie, bot_series, bot_anime, bot_bob])
    await db_session.flush()

    # Configure distinct settings and sponsors
    db_session.add_all([
        ClientBotSettings(client_bot_id=bot_movie.id, start_message="Welcome to Movies!"),
        ClientBotSettings(client_bot_id=bot_series.id, start_message="Welcome to Series!"),
        ClientBotSettings(client_bot_id=bot_anime.id, start_message="Welcome to Anime!"),
        SponsorConfig(client_bot_id=bot_movie.id, is_enabled=True, button_text="Unlock Movie"),
        SponsorConfig(client_bot_id=bot_series.id, is_enabled=True, button_text="Unlock Series"),
        SponsorConfig(client_bot_id=bot_anime.id, is_enabled=False, button_text="Unlock Anime"),
    ])
    await db_session.commit()

    management_svc = ClientBotManagementService(db_session)
    lifecycle_svc = ClientBotLifecycleService(db_session)
    viewer_svc = ViewerService(db_session)
    unlock_svc = ViewerUnlockService(db_session)
    video_repo = VideoRepository(db_session)
    viewer_repo = ViewerRepository(db_session)

    # =========================================================================
    # 1. Multi-Bot Listing & Pagination
    # =========================================================================
    bots_a, total_a, counts_a = await management_svc.list_client_bots(client_a.id, page=1, page_size=10)
    assert total_a == 3
    assert len(bots_a) == 3
    assert counts_a["active"] == 3

    bots_b, total_b, counts_b = await management_svc.list_client_bots(client_b.id, page=1, page_size=10)
    assert total_b == 1
    assert len(bots_b) == 1
    assert bots_b[0].username == "BobsNewsBot"

    # =========================================================================
    # 2. Independent Videos per Bot
    # =========================================================================
    vid_movie = Video(
        client_bot_id=bot_movie.id,
        status=VideoStatus.READY,
        telegram_file_id="tg_file_movie_1",
        telegram_file_unique_id="uniq_movie_1",
        caption="Movie Post #1",
    )
    vid_series = Video(
        client_bot_id=bot_series.id,
        status=VideoStatus.READY,
        telegram_file_id="tg_file_series_1",
        telegram_file_unique_id="uniq_series_1",
        caption="Series Post #1",
    )
    db_session.add_all([vid_movie, vid_series])
    await db_session.commit()

    movie_videos = await video_repo.list_ready_by_bot(bot_movie.id)
    assert len(movie_videos) == 1
    assert movie_videos[0].caption == "Movie Post #1"

    series_videos = await video_repo.list_ready_by_bot(bot_series.id)
    assert len(series_videos) == 1
    assert series_videos[0].caption == "Series Post #1"

    anime_videos = await video_repo.list_ready_by_bot(bot_anime.id)
    assert len(anime_videos) == 0

    # =========================================================================
    # 3. Independent Viewers & Independent Block Status
    # =========================================================================
    # Same Telegram user (User #77777) joins MovieWorldBot and SeriesHubBot
    mock_tg = AsyncMock(spec=TelegramClient)

    await viewer_svc.handle_viewer_start(
        client_bot=bot_movie,
        telegram_user_id=77777,
        chat_id=77777,
        telegram_client=mock_tg,
        username="viewer_john",
    )
    await viewer_svc.handle_viewer_start(
        client_bot=bot_series,
        telegram_user_id=77777,
        chat_id=77777,
        telegram_client=mock_tg,
        username="viewer_john",
    )

    # Verify separate viewer rows in DB
    vw_movie = await viewer_repo.get_by_bot_and_telegram_user(bot_movie.id, 77777)
    vw_series = await viewer_repo.get_by_bot_and_telegram_user(bot_series.id, 77777)
    assert vw_movie is not None
    assert vw_series is not None
    assert vw_movie.id != vw_series.id
    assert vw_movie.status == ViewerStatus.ACTIVE
    assert vw_series.status == ViewerStatus.ACTIVE

    # User blocks MovieWorldBot -> marks only MovieWorldBot viewer as BLOCKED
    await viewer_svc.mark_viewer_blocked(client_bot_id=bot_movie.id, telegram_user_id=77777)
    await db_session.refresh(vw_movie)
    await db_session.refresh(vw_series)
    assert vw_movie.status == ViewerStatus.BLOCKED
    assert vw_series.status == ViewerStatus.ACTIVE  # SeriesHubBot viewer must remain ACTIVE

    # =========================================================================
    # 4. Independent Lifecycle (Pausing MovieWorldBot does not affect Series/Anime)
    # =========================================================================
    pause_ok, _, paused_movie = await lifecycle_svc.pause_bot(bot_movie.id, client_a.id)
    assert pause_ok is True
    assert paused_movie.status == ClientBotStatus.PAUSED

    await db_session.refresh(bot_series)
    await db_session.refresh(bot_anime)
    assert bot_series.status == ClientBotStatus.ACTIVE
    assert bot_anime.status == ClientBotStatus.ACTIVE

    # =========================================================================
    # 5. Cross-Bot Unlock Delivery Rejection
    # =========================================================================
    # Viewer attempts to unlock Movie video on SeriesHubBot
    mock_unlock_tg = AsyncMock(spec=TelegramClient)
    unlock_res = await unlock_svc.handle_unlock_request(
        client_bot=bot_series,
        telegram_user_id=77777,
        chat_id=77777,
        payload=f"unlock_{vid_movie.public_id}",
        actor_data={"id": 77777},
        telegram_client=mock_unlock_tg,
    )
    assert unlock_res["ok"] is False
    assert unlock_res["error"] == "video_not_found"
    mock_unlock_tg.send_message.assert_called_once()
    assert "not available" in mock_unlock_tg.send_message.call_args.kwargs["text"].lower()

    # =========================================================================
    # 6. Cross-Client Bot Management Access Denial
    # =========================================================================
    # Client B tries to view or manage Client A's MovieWorldBot
    detail_ok, detail_data, detail_err = await management_svc.get_bot_detail(
        client_id=client_b.id,
        client_bot_id=bot_movie.id,
    )
    assert detail_ok is False
    assert detail_data is None
    assert "access denied" in detail_err.lower() or "not found" in detail_err.lower()
