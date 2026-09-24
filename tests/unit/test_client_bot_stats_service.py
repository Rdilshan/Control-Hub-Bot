"""Unit tests for ClientBotStatsService and per-bot isolation."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    BroadcastStatus,
    CatchupStatus,
    ProcessingStatus,
    VideoStatus,
    ViewerStatus,
)
from app.db.models.broadcast import Broadcast
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.db.models.viewer import Viewer
from app.db.models.viewer_catchup import ViewerCatchup
from app.services.client_bot_stats_service import ClientBotStatsService


@pytest.mark.asyncio
async def test_client_bot_stats_per_bot_isolation(db_session: AsyncSession):
    """Verifies that ClientBotStatsService queries are strictly scoped to client_bot_id."""
    # 1. Setup Client and two distinct bots
    client = Client(telegram_user_id=1001, username="owner_alice")
    db_session.add(client)
    await db_session.flush()

    bot_a = ClientBot(client_id=client.id, telegram_bot_id=2001, username="BotA", display_name="Bot A")
    bot_b = ClientBot(client_id=client.id, telegram_bot_id=2002, username="BotB", display_name="Bot B")
    db_session.add_all([bot_a, bot_b])
    await db_session.flush()

    # 2. Add viewers to Bot A (2 active, 1 blocked) and Bot B (5 active)
    v_a1 = Viewer(client_bot_id=bot_a.id, telegram_user_id=3001, status=ViewerStatus.ACTIVE)
    v_a2 = Viewer(client_bot_id=bot_a.id, telegram_user_id=3002, status=ViewerStatus.ACTIVE)
    v_a3 = Viewer(client_bot_id=bot_a.id, telegram_user_id=3003, status=ViewerStatus.BLOCKED)

    v_b1 = Viewer(client_bot_id=bot_b.id, telegram_user_id=4001, status=ViewerStatus.ACTIVE)
    v_b2 = Viewer(client_bot_id=bot_b.id, telegram_user_id=4002, status=ViewerStatus.ACTIVE)
    v_b3 = Viewer(client_bot_id=bot_b.id, telegram_user_id=4003, status=ViewerStatus.ACTIVE)
    db_session.add_all([v_a1, v_a2, v_a3, v_b1, v_b2, v_b3])

    # 3. Add videos: Bot A (1 ready, 1 failed), Bot B (2 ready)
    vid_a1 = Video(client_bot_id=bot_a.id, status=VideoStatus.READY, telegram_file_id="fa1", telegram_file_unique_id="ua1")
    vid_a2 = Video(client_bot_id=bot_a.id, status=VideoStatus.FAILED, telegram_file_id="fa2", telegram_file_unique_id="ua2")
    vid_b1 = Video(client_bot_id=bot_b.id, status=VideoStatus.READY, telegram_file_id="fb1", telegram_file_unique_id="ub1")
    db_session.add_all([vid_a1, vid_a2, vid_b1])

    # 4. Add broadcasts: Bot A (1 running LIVE), Bot B (0)
    bcast_a = Broadcast(
        client_bot_id=bot_a.id,
        video_id=1,
        broadcast_type="LIVE",
        status=BroadcastStatus.RUNNING,
        total_targets=10,
    )
    db_session.add(bcast_a)

    # 5. Add catchup: Bot A (1 running), Bot B (1 completed)
    cu_a = ViewerCatchup(client_bot_id=bot_a.id, viewer_id=1, status=CatchupStatus.RUNNING)
    cu_b = ViewerCatchup(client_bot_id=bot_b.id, viewer_id=4, status=CatchupStatus.COMPLETED)
    db_session.add_all([cu_a, cu_b])

    await db_session.commit()

    # Test Service for Bot A
    service = ClientBotStatsService(db_session)
    stats_a = await service.get_stats_summary(bot_a.id, bypass_cache=True)

    assert stats_a["users"]["total"] == 3
    assert stats_a["users"]["active"] == 2
    assert stats_a["users"]["blocked"] == 1
    assert stats_a["videos"]["total"] == 2
    assert stats_a["videos"]["ready"] == 1
    assert stats_a["videos"]["failed"] == 1
    assert stats_a["broadcasts"]["live_running"] == 1
    assert stats_a["broadcasts"]["catchup_running"] == 1

    # Test Service for Bot B
    stats_b = await service.get_stats_summary(bot_b.id, bypass_cache=True)
    assert stats_b["users"]["total"] == 3
    assert stats_b["users"]["active"] == 3
    assert stats_b["users"]["blocked"] == 0
    assert stats_b["videos"]["total"] == 1
    assert stats_b["videos"]["ready"] == 1
    assert stats_b["broadcasts"]["live_running"] == 0
    assert stats_b["broadcasts"]["catchup_running"] == 0
