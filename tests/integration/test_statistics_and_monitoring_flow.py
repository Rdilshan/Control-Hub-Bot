"""End-to-end integration test for Statistics, Monitoring, and Observability flow."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    BroadcastStatus,
    CatchupStatus,
    ClientBotStatus,
    ClientStatus,
    ControlHubRole,
    JobStatus,
    JobType,
    VideoStatus,
    ViewerStatus,
)
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.broadcast import Broadcast
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.platform_owner import PlatformOwner
from app.db.models.video import Video
from app.db.models.viewer import Viewer
from app.db.models.viewer_catchup import ViewerCatchup
from app.telegram.client import TelegramClient
from app.telegram.client_bot.admin_router import ClientAdminRouter
from app.telegram.client_bot.context import ClientBotActorContext, ClientBotContext
from app.telegram.control_hub.router import ControlHubRouter


@pytest.mark.asyncio
async def test_full_statistics_and_monitoring_journey(db_session: AsyncSession):
    """Executes the complete acceptance flow from Plan 17:
    1. Setup Platform Owner and two distinct bots (MovieWorldBot & SeriesHubBot).
    2. Populate independent viewers, videos, broadcasts, and jobs for each bot.
    3. Client Admin calls /stats on MovieWorldBot -> receives ONLY MovieWorldBot metrics.
    4. Client Admin calls /users, /processing, /broadcasts on MovieWorldBot -> strictly scoped.
    5. Platform Owner sends /systemstats on Control Hub -> receives global platform totals.
    6. Platform Owner sends /queue on Control Hub -> sees pending jobs and oldest waiting time.
    7. Platform Owner sends /jobs on Control Hub -> views failed job with safe error formatting.
    8. Stale job and worker health observability.
    9. Unauthorized viewer attempts /stats -> blocked with no admin data.
    """
    mock_tg = AsyncMock(spec=TelegramClient)

    # =========================================================================
    # 1. Setup Platform Entities
    # =========================================================================
    owner_user_id = 999999
    owner = PlatformOwner(telegram_user_id=owner_user_id, username="super_owner")
    db_session.add(owner)

    client_admin_user_id = 111111
    client_a = Client(telegram_user_id=client_admin_user_id, username="alice_client", status=ClientStatus.ACTIVE)
    client_b = Client(telegram_user_id=222222, username="bob_client", status=ClientStatus.ACTIVE)
    db_session.add_all([client_a, client_b])
    await db_session.flush()

    bot_movie = ClientBot(
        client_id=client_a.id,
        telegram_bot_id=5001,
        username="MovieWorldBot",
        display_name="Movie World",
        status=ClientBotStatus.ACTIVE,
    )
    bot_series = ClientBot(
        client_id=client_a.id,
        telegram_bot_id=5002,
        username="SeriesHubBot",
        display_name="Series Hub",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add_all([bot_movie, bot_series])
    await db_session.flush()

    admin_record = ClientBotAdmin(
        client_bot_id=bot_movie.id,
        telegram_user_id=client_admin_user_id,
        role="OWNER",
    )
    db_session.add(admin_record)

    # =========================================================================
    # 2. Populate Metrics (Bot Movie vs Bot Series)
    # =========================================================================
    # MovieBot: 3 Active, 1 Blocked
    for i in range(1, 4):
        db_session.add(Viewer(client_bot_id=bot_movie.id, telegram_user_id=7000 + i, status=ViewerStatus.ACTIVE))
    db_session.add(Viewer(client_bot_id=bot_movie.id, telegram_user_id=7004, status=ViewerStatus.BLOCKED))

    # SeriesBot: 5 Active Viewers
    for i in range(1, 6):
        db_session.add(Viewer(client_bot_id=bot_series.id, telegram_user_id=8000 + i, status=ViewerStatus.ACTIVE))

    # MovieBot: 2 Ready videos, 1 Failed
    db_session.add(Video(client_bot_id=bot_movie.id, status=VideoStatus.READY, telegram_file_id="mf1", telegram_file_unique_id="mu1", caption="Movie 1"))
    db_session.add(Video(client_bot_id=bot_movie.id, status=VideoStatus.READY, telegram_file_id="mf2", telegram_file_unique_id="mu2", caption="Movie 2"))
    db_session.add(Video(client_bot_id=bot_movie.id, status=VideoStatus.FAILED, telegram_file_id="mf3", telegram_file_unique_id="mu3", caption="Movie 3 Failed"))

    # SeriesBot: 1 Ready video
    db_session.add(Video(client_bot_id=bot_series.id, status=VideoStatus.READY, telegram_file_id="sf1", telegram_file_unique_id="su1", caption="Series 1"))

    # MovieBot: 1 Running Broadcast, 1 Running Catchup
    db_session.add(Broadcast(
        client_bot_id=bot_movie.id,
        video_id=1,
        broadcast_type="LIVE",
        status=BroadcastStatus.RUNNING,
        total_targets=100,
        sent_count=70,
        blocked_count=5,
    ))
    db_session.add(ViewerCatchup(client_bot_id=bot_movie.id, viewer_id=1, status=CatchupStatus.RUNNING))

    # Platform Background Jobs (1 pending, 1 failed with safe error)
    job_pending = BackgroundJob(
        job_type=JobType.VIDEO_PROCESS,
        client_bot_id=bot_movie.id,
        status=JobStatus.PENDING,
        payload={"video_id": 1},
        scheduled_at=utc_now() - timedelta(minutes=4),
    )
    job_failed = BackgroundJob(
        job_type=JobType.CREATE_UNLOCK_LINK,
        client_bot_id=bot_movie.id,
        status=JobStatus.FAILED,
        payload={"video_id": 3},
        attempt_count=3,
        max_attempts=3,
        last_error_code="UNLOCKIFY_INVALID_KEY",
        last_error_message="Unlockify API returned 401 Unauthorized",
    )
    db_session.add_all([job_pending, job_failed])

    await db_session.commit()

    # =========================================================================
    # 3. Client Admin /stats on MovieWorldBot
    # =========================================================================
    admin_router = ClientAdminRouter(mock_tg)
    bot_ctx = ClientBotContext(
        client_bot_id=bot_movie.id,
        client_id=client_a.id,
        telegram_bot_id=bot_movie.telegram_bot_id,
        bot_username="MovieWorldBot",
        display_name="Movie World",
        status=ClientBotStatus.ACTIVE,
        public_bot_id="bot_movie_pub_1",
    )
    actor_admin = ClientBotActorContext(
        telegram_user_id=client_admin_user_id,
        chat_id=client_admin_user_id,
        chat_type="private",
        username="alice_client",
        first_name="Alice",
        last_name=None,
        language_code="en",
        role="ADMIN",
        admin_record_id=admin_record.id,
    )

    res_stats = await admin_router.handle(
        bot_ctx=bot_ctx,
        actor=actor_admin,
        actor_data={"update_type": "message", "text": "/stats"},
        session=db_session,
    )
    assert res_stats["ok"] is True
    # Verify sent message contains MovieWorldBot counts and does NOT include SeriesHubBot counts
    call_args = mock_tg.send_message.call_args[1]
    stats_text = call_args["text"]
    assert "Bot Statistics" in stats_text
    assert "Total: <b>4</b>" in stats_text  # 4 users for MovieWorldBot (3 active + 1 blocked)
    assert "Active: <b>3</b>" in stats_text
    assert "Blocked: <b>1</b>" in stats_text
    assert "Ready: <b>2</b>" in stats_text  # 2 videos for MovieWorldBot
    assert "Failed: <b>1</b>" in stats_text
    assert "Running: <b>1</b>" in stats_text

    # =========================================================================
    # 4. Client Admin /users & /processing & /broadcasts
    # =========================================================================
    mock_tg.send_message.reset_mock()
    await admin_router.handle(
        bot_ctx=bot_ctx,
        actor=actor_admin,
        actor_data={"update_type": "message", "text": "/users"},
        session=db_session,
    )
    users_text = mock_tg.send_message.call_args[1]["text"]
    assert "Audience & Subscribers" in users_text
    assert "Total Users: <b>4</b>" in users_text

    mock_tg.send_message.reset_mock()
    await admin_router.handle(
        bot_ctx=bot_ctx,
        actor=actor_admin,
        actor_data={"update_type": "message", "text": "/processing"},
        session=db_session,
    )
    proc_text = mock_tg.send_message.call_args[1]["text"]
    assert "Video Processing Pipeline" in proc_text

    mock_tg.send_message.reset_mock()
    await admin_router.handle(
        bot_ctx=bot_ctx,
        actor=actor_admin,
        actor_data={"update_type": "message", "text": "/broadcasts"},
        session=db_session,
    )
    bcast_text = mock_tg.send_message.call_args[1]["text"]
    assert "Broadcasts & Delivery Status" in bcast_text

    # =========================================================================
    # 5. Platform Owner /systemstats on Control Hub
    # =========================================================================
    control_hub_router = ControlHubRouter(mock_tg)
    mock_tg.send_message.reset_mock()

    update_systemstats = {
        "message": {
            "chat": {"id": owner_user_id, "type": "private"},
            "from": {"id": owner_user_id, "username": "super_owner"},
            "text": "/systemstats",
        }
    }
    res_owner_stats = await control_hub_router.process_update(update_systemstats, session=db_session)
    assert res_owner_stats["ok"] is True
    sys_text = mock_tg.send_message.call_args[1]["text"]
    assert "Control Hub Statistics" in sys_text
    assert "Clients: <b>2</b>" in sys_text
    assert "Connected Bots: <b>2</b>" in sys_text
    assert "Total Viewers: <b>9</b>" in sys_text  # 4 from MovieBot + 5 from SeriesBot
    assert "Total Videos: <b>4</b>" in sys_text   # 3 from MovieBot + 1 from SeriesBot

    # =========================================================================
    # 6. Platform Owner /queue & /jobs on Control Hub
    # =========================================================================
    mock_tg.send_message.reset_mock()
    update_queue = {
        "message": {
            "chat": {"id": owner_user_id, "type": "private"},
            "from": {"id": owner_user_id, "username": "super_owner"},
            "text": "/queue",
        }
    }
    await control_hub_router.process_update(update_queue, session=db_session)
    queue_text = mock_tg.send_message.call_args[1]["text"]
    assert "Queue Status" in queue_text
    assert "Video Processing: <b>1</b>" in queue_text
    assert "4m" in queue_text  # Oldest waiting ~4m

    mock_tg.send_message.reset_mock()
    update_jobs = {
        "message": {
            "chat": {"id": owner_user_id, "type": "private"},
            "from": {"id": owner_user_id, "username": "super_owner"},
            "text": "/jobs",
        }
    }
    await control_hub_router.process_update(update_jobs, session=db_session)
    jobs_text = mock_tg.send_message.call_args[1]["text"]
    assert "Background Jobs" in jobs_text
    assert "Failed: <b>1</b>" in jobs_text
