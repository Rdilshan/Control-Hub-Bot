"""Unit tests for ClientBotManagementService, ClientBotSelectorService, and ClientAccountBotSummaryService."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
    ClientBotStatus,
    ClientStatus,
    VideoStatus,
    ViewerStatus,
)
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_settings import ClientBotSettings
from app.db.models.sponsor_config import SponsorConfig
from app.db.models.video import Video
from app.db.models.viewer import Viewer
from app.services.client_account_bot_summary_service import ClientAccountBotSummaryService
from app.services.client_bot_management_service import ClientBotManagementService
from app.services.client_bot_selector_service import ClientBotSelectorService


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def multi_bot_setup(db_session: AsyncSession):
    # Create Client A
    client_a = Client(telegram_user_id=11001, username="client_alice", status=ClientStatus.ACTIVE)
    # Create Client B
    client_b = Client(telegram_user_id=22001, username="client_bob", status=ClientStatus.ACTIVE)
    db_session.add_all([client_a, client_b])
    await db_session.flush()

    # Create 3 bots for Client A
    bots_a = []
    statuses = [ClientBotStatus.ACTIVE, ClientBotStatus.PAUSED, ClientBotStatus.INVALID_TOKEN]
    for i, st in enumerate(statuses, 1):
        b = ClientBot(
            client_id=client_a.id,
            telegram_bot_id=1000 + i,
            username=f"alice_bot_{i}",
            display_name=f"Alice Bot {i}",
            token_encrypted=encrypt_token(f"token_alice_{i}"),
            status=st,
        )
        db_session.add(b)
        await db_session.flush()

        settings = ClientBotSettings(
            client_bot_id=b.id,
            start_message=f"Welcome to Alice Bot {i}",
            default_message=f"Default reply for Alice Bot {i}",
        )
        sponsor = SponsorConfig(
            client_bot_id=b.id,
            is_enabled=(i == 1),
            button_text=f"Unlock Alice {i}",
        )
        db_session.add_all([settings, sponsor])

        # Add viewers and videos to Bot 1
        if i == 1:
            for v_idx in range(5):
                vw = Viewer(
                    client_bot_id=b.id,
                    telegram_user_id=5000 + v_idx,
                    status=ViewerStatus.ACTIVE,
                )
                db_session.add(vw)
            for vid_idx in range(3):
                vid = Video(
                    client_bot_id=b.id,
                    status=VideoStatus.READY,
                    telegram_file_id=f"file_a_{vid_idx}",
                    telegram_file_unique_id=f"uniq_a_{vid_idx}",
                )
                db_session.add(vid)

        bots_a.append(b)

    # Create 1 bot for Client B
    bot_b = ClientBot(
        client_id=client_b.id,
        telegram_bot_id=2001,
        username="bob_bot_1",
        display_name="Bob Bot 1",
        token_encrypted=encrypt_token("token_bob_1"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot_b)
    await db_session.commit()

    return {
        "client_a": client_a,
        "client_b": client_b,
        "bots_a": bots_a,
        "bot_b": bot_b,
    }


# ============================================================================
# 1. Multi-Bot Listing & Pagination Tests
# ============================================================================

@pytest.mark.asyncio
async def test_list_client_bots_pagination(db_session: AsyncSession, multi_bot_setup):
    client_a = multi_bot_setup["client_a"]
    service = ClientBotManagementService(db_session)

    # Fetch page 1 with page_size=2
    bots_page1, total, counts = await service.list_client_bots(
        client_id=client_a.id,
        page=1,
        page_size=2,
    )

    assert total == 3
    assert len(bots_page1) == 2
    assert bots_page1[0].username == "alice_bot_1"
    assert bots_page1[1].username == "alice_bot_2"

    # Status counts verification
    assert counts["total"] == 3
    assert counts["active"] == 1
    assert counts["paused"] == 1
    assert counts["needs_attention"] == 1

    # Fetch page 2 with page_size=2
    bots_page2, total, _ = await service.list_client_bots(
        client_id=client_a.id,
        page=2,
        page_size=2,
    )
    assert len(bots_page2) == 1
    assert bots_page2[0].username == "alice_bot_3"


# ============================================================================
# 2. Bot Detail & Ownership Guard Tests
# ============================================================================

@pytest.mark.asyncio
async def test_get_bot_detail_owner_access(db_session: AsyncSession, multi_bot_setup):
    client_a = multi_bot_setup["client_a"]
    bot_a1 = multi_bot_setup["bots_a"][0]
    service = ClientBotManagementService(db_session)

    success, detail, err = await service.get_bot_detail(
        client_id=client_a.id,
        client_bot_id=bot_a1.id,
    )

    assert success is True
    assert err is None
    assert detail["username"] == "alice_bot_1"
    assert detail["status"] == ClientBotStatus.ACTIVE.value
    assert detail["start_message"] == "Welcome to Alice Bot 1"
    assert detail["sponsor_enabled"] is True
    assert detail["viewers_count"] == 5
    assert detail["videos_count"] == 3


@pytest.mark.asyncio
async def test_get_bot_detail_cross_client_access_denied(db_session: AsyncSession, multi_bot_setup):
    client_a = multi_bot_setup["client_a"]
    bot_b = multi_bot_setup["bot_b"]
    service = ClientBotManagementService(db_session)

    # Client A attempts to access Client B's bot
    success, detail, err = await service.get_bot_detail(
        client_id=client_a.id,
        client_bot_id=bot_b.id,
    )

    assert success is False
    assert detail is None
    assert "access denied" in err.lower() or "not found" in err.lower()


# ============================================================================
# 3. Account-Level Aggregate Summary Tests
# ============================================================================

@pytest.mark.asyncio
async def test_client_aggregate_summary(db_session: AsyncSession, multi_bot_setup):
    client_a = multi_bot_setup["client_a"]
    summary_service = ClientAccountBotSummaryService(db_session)

    summary = await summary_service.get_account_summary(client_a.id)

    assert summary["total_bots"] == 3
    assert summary["active_bots"] == 1
    assert summary["paused_bots"] == 1
    assert summary["needs_attention_bots"] == 1
    assert summary["total_viewers"] == 5
    assert summary["total_videos"] == 3


# ============================================================================
# 4. Bot Selector UI & Context Caching Tests
# ============================================================================

@pytest.mark.asyncio
async def test_bot_selector_keyboard_and_context(db_session: AsyncSession, multi_bot_setup):
    client_a = multi_bot_setup["client_a"]
    bot_a1 = multi_bot_setup["bots_a"][0]
    selector_service = ClientBotSelectorService(db_session)

    # Build keyboard with page_size=2
    keyboard, total_pages, total_count = await selector_service.build_bot_selector_keyboard(
        client_id=client_a.id,
        page=1,
        page_size=2,
    )

    assert total_count == 3
    assert total_pages == 2
    # 2 bot buttons + 1 navigation row
    assert len(keyboard) == 3
    assert "alice_bot_1" in keyboard[0][0]["text"]
    assert keyboard[0][0]["callback_data"] == f"client:bot:select:{bot_a1.id}"
    assert "Next ▶" in keyboard[2][0]["text"]

    # Test context caching
    await selector_service.store_selected_bot(client_a.id, bot_a1.id)
    retrieved_id = await selector_service.get_selected_bot(client_a.id)
    assert retrieved_id == bot_a1.id

    await selector_service.clear_selected_bot(client_a.id)
    assert await selector_service.get_selected_bot(client_a.id) is None
