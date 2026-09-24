"""Unit tests for VideoCreationService and video intake workflow."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import ClientBotStatus, JobStatus, JobType, ProcessingStatus, VideoStatus
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.sponsor_config import SponsorConfig
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository
from app.services.video_creation_service import VideoCreationService


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
async def test_start_create_video_session_guards(db_session: AsyncSession):
    client = Client(telegram_user_id=101, username="client_owner")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=90901,
        username="MediaBot",
        public_id="b_media101",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    # 1. Sponsor not configured -> fails guard
    mock_tg = MagicMock()
    mock_tg.send_message = AsyncMock(return_value={"message_id": 1})

    service = VideoCreationService(db_session)
    res_no_sponsor = await service.start_create_video_session(
        client_bot=bot,
        telegram_user_id=101,
        chat_id=101,
        telegram_client=mock_tg,
    )
    assert res_no_sponsor["ok"] is False
    assert res_no_sponsor["error"] == "sponsor_required"
    assert "Sponsor Configuration Required" in mock_tg.send_message.call_args.kwargs["text"]

    # 2. Configure Sponsor -> succeeds and sets state
    sponsor = SponsorConfig(client_bot_id=bot.id, is_enabled=True, sponsor_url="https://unlockify.ink/test")
    db_session.add(sponsor)
    await db_session.commit()

    res_ok = await service.start_create_video_session(
        client_bot=bot,
        telegram_user_id=101,
        chat_id=101,
        telegram_client=mock_tg,
    )
    assert res_ok["ok"] is True
    assert res_ok["action"] == "create_video_prompt_sent"

    state = await service.get_creation_state(bot.id, 101)
    assert state == "WAITING_FOR_VIDEO"


@pytest.mark.asyncio
async def test_process_video_intake_non_video_warnings(db_session: AsyncSession):
    client = Client(telegram_user_id=102, username="client_owner2")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=90902,
        username="MediaBot2",
        public_id="b_media102",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    sponsor = SponsorConfig(client_bot_id=bot.id, is_enabled=True, sponsor_url="https://unlockify.ink/test")
    db_session.add(sponsor)
    await db_session.commit()

    mock_tg = MagicMock()
    mock_tg.send_message = AsyncMock(return_value={"message_id": 2})

    service = VideoCreationService(db_session)
    await service.set_creation_state(bot.id, 102, "WAITING_FOR_VIDEO")

    # 1. Admin sends document/file instead of video
    doc_actor_data = {
        "update_type": "message",
        "telegram_user_id": 102,
        "chat_id": 102,
        "document": {"file_id": "doc_123", "file_name": "movie.mkv"},
        "video": None,
        "text": None,
    }
    res_doc = await service.process_video_intake(
        client_bot=bot,
        telegram_user_id=102,
        chat_id=102,
        admin_id=None,
        actor_data=doc_actor_data,
        telegram_client=mock_tg,
    )
    assert res_doc["action"] == "document_warning_sent"
    assert "Please send as a Video" in mock_tg.send_message.call_args.kwargs["text"]
    assert await service.get_creation_state(bot.id, 102) == "WAITING_FOR_VIDEO"

    # 2. Admin sends plain text
    txt_actor_data = {
        "update_type": "message",
        "telegram_user_id": 102,
        "chat_id": 102,
        "document": None,
        "video": None,
        "text": "random message text",
    }
    res_txt = await service.process_video_intake(
        client_bot=bot,
        telegram_user_id=102,
        chat_id=102,
        admin_id=None,
        actor_data=txt_actor_data,
        telegram_client=mock_tg,
    )
    assert res_txt["action"] == "non_video_warning_sent"

    # 3. Admin sends /cancel
    cancel_actor_data = {
        "update_type": "message",
        "telegram_user_id": 102,
        "chat_id": 102,
        "document": None,
        "video": None,
        "text": "/cancel",
    }
    res_cancel = await service.process_video_intake(
        client_bot=bot,
        telegram_user_id=102,
        chat_id=102,
        admin_id=None,
        actor_data=cancel_actor_data,
        telegram_client=mock_tg,
    )
    assert res_cancel["action"] == "create_video_cancelled"
    assert await service.get_creation_state(bot.id, 102) is None


@pytest.mark.asyncio
async def test_process_video_intake_success_and_job_creation(db_session: AsyncSession):
    client = Client(telegram_user_id=103, username="client_owner3")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=90903,
        username="MediaBot3",
        public_id="b_media103",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    sponsor = SponsorConfig(client_bot_id=bot.id, is_enabled=True, sponsor_url="https://unlockify.ink/test")
    db_session.add(sponsor)
    await db_session.commit()

    mock_tg = MagicMock()
    mock_tg.send_message = AsyncMock(return_value={"message_id": 3})

    service = VideoCreationService(db_session)
    await service.set_creation_state(bot.id, 103, "WAITING_FOR_VIDEO")

    # Admin sends valid video
    video_actor_data = {
        "update_type": "message",
        "telegram_user_id": 103,
        "chat_id": 103,
        "message_id": 8801,
        "caption": "🎬 Epic Action Trailer (2026)",
        "video": {
            "file_id": "tg_vid_file_9988",
            "file_unique_id": "uniq_vid_9988",
            "file_size": 25000000,
            "duration": 125,
            "width": 1920,
            "height": 1080,
            "mime_type": "video/mp4",
            "file_name": "trailer_hd.mp4",
            "thumbnail": {"file_id": "thumb_file_123"},
        },
    }

    res = await service.process_video_intake(
        client_bot=bot,
        telegram_user_id=103,
        chat_id=103,
        admin_id=None,
        actor_data=video_actor_data,
        telegram_client=mock_tg,
    )
    assert res["ok"] is True
    assert res["action"] == "video_created"
    assert "video_id" in res

    # 1. Session state must be closed immediately
    assert await service.get_creation_state(bot.id, 103) is None

    # 2. Check Database: Video record exists
    video_repo = VideoRepository(db_session)
    vid = await video_repo.get_by_id_and_bot(res["video_id"], bot.id)
    assert vid is not None
    assert vid.telegram_file_id == "tg_vid_file_9988"
    assert vid.telegram_file_unique_id == "uniq_vid_9988"
    assert vid.duration_seconds == 125
    assert vid.caption == "🎬 Epic Action Trailer (2026)"
    assert vid.status == VideoStatus.RECEIVED

    # 3. Check Database: VideoProcessing record exists
    stmt_proc = db_session.execute
    proc = await db_session.get(VideoProcessing, vid.id)
    assert proc is not None
    assert proc.thumbnail_file_id == "thumb_file_123"
    assert proc.status == ProcessingStatus.PENDING

    # 4. Check Database: Background Job created
    job_repo = BackgroundJobRepository(db_session)
    jobs, total = await job_repo.list_paginated(job_type=JobType.VIDEO_PROCESS)
    assert total >= 1
    matching_job = [j for j in jobs if j.video_id == vid.id][0]
    assert matching_job.job_type == JobType.VIDEO_PROCESS
    assert matching_job.status == JobStatus.PENDING
    assert matching_job.payload["thumbnail_file_id"] == "thumb_file_123"

    # 5. Success confirmation sent to admin
    assert "Video Received" in mock_tg.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_process_video_intake_missing_thumbnail(db_session: AsyncSession):
    """Section 114: Video without source thumbnail is accepted successfully."""
    client = Client(telegram_user_id=104, username="client_owner4")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=90904,
        username="MediaBot4",
        public_id="b_media104",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    sponsor = SponsorConfig(client_bot_id=bot.id, is_enabled=True, sponsor_url="https://unlockify.ink/test")
    db_session.add(sponsor)
    await db_session.commit()

    mock_tg = MagicMock()
    mock_tg.send_message = AsyncMock(return_value={"message_id": 4})

    service = VideoCreationService(db_session)
    await service.set_creation_state(bot.id, 104, "WAITING_FOR_VIDEO")

    # Admin sends valid video with NO thumbnail
    video_actor_data = {
        "update_type": "message",
        "telegram_user_id": 104,
        "chat_id": 104,
        "message_id": 8802,
        "video": {
            "file_id": "tg_vid_nothumb_1",
            "file_unique_id": "uniq_nothumb_1",
            "file_size": 15000000,
            "duration": 60,
        },
    }

    res = await service.process_video_intake(
        client_bot=bot,
        telegram_user_id=104,
        chat_id=104,
        admin_id=None,
        actor_data=video_actor_data,
        telegram_client=mock_tg,
    )
    assert res["ok"] is True
    assert res["action"] == "video_created"

    video_repo = VideoRepository(db_session)
    vid = await video_repo.get_by_id_and_bot(res["video_id"], bot.id)
    assert vid is not None
    assert vid.source_thumbnail_file_id is None
    assert vid.status == VideoStatus.RECEIVED


@pytest.mark.asyncio
async def test_process_video_intake_duplicate_webhook(db_session: AsyncSession):
    """Section 118: Duplicate webhook message is skipped without duplicate DB records."""
    client = Client(telegram_user_id=105, username="client_owner5")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=90905,
        username="MediaBot5",
        public_id="b_media105",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    sponsor = SponsorConfig(client_bot_id=bot.id, is_enabled=True, sponsor_url="https://unlockify.ink/test")
    db_session.add(sponsor)
    await db_session.commit()

    mock_tg = MagicMock()
    mock_tg.send_message = AsyncMock(return_value={"message_id": 5})

    service = VideoCreationService(db_session)
    await service.set_creation_state(bot.id, 105, "WAITING_FOR_VIDEO")

    video_actor_data = {
        "update_type": "message",
        "telegram_user_id": 105,
        "chat_id": 105,
        "message_id": 9901,
        "video": {
            "file_id": "tg_vid_dup_1",
            "file_unique_id": "uniq_dup_1",
        },
    }

    # First delivery: creates video
    res1 = await service.process_video_intake(
        client_bot=bot,
        telegram_user_id=105,
        chat_id=105,
        admin_id=None,
        actor_data=video_actor_data,
        telegram_client=mock_tg,
    )
    assert res1["ok"] is True
    assert res1["action"] == "video_created"

    # Second delivery (duplicate update): session state set again or received
    await service.set_creation_state(bot.id, 105, "WAITING_FOR_VIDEO")
    res2 = await service.process_video_intake(
        client_bot=bot,
        telegram_user_id=105,
        chat_id=105,
        admin_id=None,
        actor_data=video_actor_data,
        telegram_client=mock_tg,
    )
    assert res2["ok"] is True
    assert res2["action"] == "duplicate_video_skipped"
    assert res2["video_id"] == res1["video_id"]

    # Verify total video count is still 1
    video_repo = VideoRepository(db_session)
    count = await video_repo.count_by_bot(bot.id)
    assert count == 1


@pytest.mark.asyncio
async def test_process_video_intake_mid_session_lifecycle_changes(db_session: AsyncSession):
    """Sections 122, 123, 124: Re-checks bot status, sponsor, and admin authorization."""
    client = Client(telegram_user_id=106, username="client_owner6")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=90906,
        username="MediaBot6",
        public_id="b_media106",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    admin = ClientBotAdmin(
        client_bot_id=bot.id,
        telegram_user_id=106,
        username="client_owner6",
        is_active=True,
    )
    sponsor = SponsorConfig(client_bot_id=bot.id, is_enabled=True, sponsor_url="https://unlockify.ink/test")
    db_session.add_all([admin, sponsor])
    await db_session.commit()

    mock_tg = MagicMock()
    mock_tg.send_message = AsyncMock(return_value={"message_id": 6})

    service = VideoCreationService(db_session)
    video_actor_data = {
        "update_type": "message",
        "telegram_user_id": 106,
        "chat_id": 106,
        "message_id": 9902,
        "video": {
            "file_id": "tg_vid_chk_1",
            "file_unique_id": "uniq_chk_1",
        },
    }

    # 1. Bot became PAUSED mid-session
    bot.status = ClientBotStatus.PAUSED
    await db_session.commit()
    await service.set_creation_state(bot.id, 106, "WAITING_FOR_VIDEO")

    res_paused = await service.process_video_intake(
        client_bot=bot,
        telegram_user_id=106,
        chat_id=106,
        admin_id=admin.id,
        actor_data=video_actor_data,
        telegram_client=mock_tg,
    )
    assert res_paused["ok"] is False
    assert res_paused["error"] == "bot_paused"

    # 2. Bot back to ACTIVE, but sponsor was disabled mid-session
    bot.status = ClientBotStatus.ACTIVE
    sponsor.is_enabled = False
    await db_session.commit()
    await service.set_creation_state(bot.id, 106, "WAITING_FOR_VIDEO")

    res_sponsor = await service.process_video_intake(
        client_bot=bot,
        telegram_user_id=106,
        chat_id=106,
        admin_id=admin.id,
        actor_data=video_actor_data,
        telegram_client=mock_tg,
    )
    assert res_sponsor["ok"] is False
    assert res_sponsor["error"] == "sponsor_required"

    # 3. Sponsor back to enabled, but admin authorization revoked mid-session
    sponsor.is_enabled = True
    admin.is_active = False
    await db_session.commit()
    await service.set_creation_state(bot.id, 106, "WAITING_FOR_VIDEO")

    res_admin = await service.process_video_intake(
        client_bot=bot,
        telegram_user_id=106,
        chat_id=106,
        admin_id=None,
        actor_data=video_actor_data,
        telegram_client=mock_tg,
    )
    assert res_admin["ok"] is False
    assert res_admin["error"] == "admin_unauthorized"


@pytest.mark.asyncio
async def test_video_ingest_dispatcher_recovery(db_session: AsyncSession):
    """Section 125, Task 08: VideoIngestDispatcher recovers orphan video records."""
    from app.workers.video_ingest_dispatcher import VideoIngestDispatcher

    client = Client(telegram_user_id=107, username="client_owner7")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=90907,
        username="MediaBot7",
        public_id="b_media107",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    # Create orphan video + processing without background job
    video_repo = VideoRepository(db_session)
    vid = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="orphan_file_id",
        telegram_file_unique_id="orphan_unique_id",
    )
    await db_session.commit()

    dispatcher = VideoIngestDispatcher(db_session)
    recovered = await dispatcher.recover_unprocessed_videos()
    assert recovered == 1

    # Check that background job now exists
    job_repo = BackgroundJobRepository(db_session)
    active_job = await job_repo.get_active_for_video(vid.id)
    assert active_job is not None
    assert active_job.status == JobStatus.PENDING
    assert active_job.job_type == JobType.VIDEO_PROCESS
