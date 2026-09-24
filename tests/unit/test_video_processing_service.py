"""Unit tests for VideoProcessingService, UnlockifyClient, PreviewPhotoService, and BroadcastCreationService."""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import (
    ClientBotStatus,
    JobStatus,
    JobType,
    ProcessingStatus,
    UnlockLinkStatus,
    VideoStatus,
)
from app.core.security import encrypt_token
from app.db.base import Base
from app.db.models.broadcast import Broadcast
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.sponsor_config import SponsorConfig
from app.db.models.unlock_link import UnlockLink
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.exceptions import (
    UnlockifyError,
    UnlockifyInvalidResponseError,
    UnlockifyNetworkError,
    UnlockifyRequestRejectedError,
    UnlockifyTimeoutError,
    ValidationError,
)
from app.telegram.errors import TelegramInvalidTokenError
from app.repositories.broadcast import BroadcastRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.unlock_link import UnlockLinkRepository
from app.repositories.video import VideoRepository
from app.repositories.video_processing import VideoProcessingRepository
from app.schemas.unlockify import UnlockifyLinkData
from app.services.broadcast_creation_service import BroadcastCreationService
from app.services.preview_photo_service import PreviewPhotoService
from app.services.unlockify_client import UnlockifyClient
from app.services.video_destination_url_service import VideoDestinationUrlService
from app.services.video_processing_service import VideoProcessingService
from app.workers.video_processing import VideoProcessingWorker


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


# ---------------------------------------------------------
# 1. VideoDestinationUrlService Tests
# ---------------------------------------------------------
def test_video_destination_url_service():
    service = VideoDestinationUrlService(base_url="https://app.controlhub.test/")
    url = service.build_destination_url("vid_abc123")
    assert url == "https://app.controlhub.test/video/vid_abc123"
    assert "token" not in url
    assert "secret" not in url


# ---------------------------------------------------------
# 2. UnlockifyClient Tests
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_unlockify_client_success():
    mock_resp = httpx.Response(
        status_code=200,
        json={
            "success": True,
            "data": {
                "id": "vlD8zKlg",
                "title": "Blockbuster Movie 2026",
                "ads_count": 1,
                "unlock_url": "https://developer.unlockify.ink/u/vlD8zKlg",
            },
        },
        request=httpx.Request("POST", "https://developer.unlockify.ink/api/v1/links"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        client = UnlockifyClient(base_url="https://developer.unlockify.ink/api/v1")
        result = await client.create_link(
            title="Blockbuster Movie 2026",
            advertisement_urls=["https://sponsor.example/ad1"],
            destination_url="https://app.controlhub.test/video/vid_abc123",
        )

        assert isinstance(result, UnlockifyLinkData)
        assert result.id == "vlD8zKlg"
        assert result.title == "Blockbuster Movie 2026"
        assert result.unlock_url == "https://developer.unlockify.ink/u/vlD8zKlg"

        mock_post.assert_called_once()
        called_kwargs = mock_post.call_args.kwargs
        assert called_kwargs["json"] == {
            "title": "Blockbuster Movie 2026",
            "advertisement_urls": ["https://sponsor.example/ad1"],
            "destination_url": "https://app.controlhub.test/video/vid_abc123",
        }


@pytest.mark.asyncio
async def test_unlockify_client_validation_errors():
    client = UnlockifyClient()
    with pytest.raises(ValidationError):
        await client.create_link(title="", advertisement_urls=["https://ad.com"], destination_url="https://dest.com")

    with pytest.raises(ValidationError):
        await client.create_link(title="Test", advertisement_urls=[], destination_url="https://dest.com")

    with pytest.raises(ValidationError):
        await client.create_link(title="Test", advertisement_urls=["https://ad.com"], destination_url="")


@pytest.mark.asyncio
async def test_unlockify_client_error_handling():
    client = UnlockifyClient()

    # 1. Timeout
    with patch("httpx.AsyncClient.post", side_effect=httpx.ReadTimeout("Timeout")):
        with pytest.raises(UnlockifyTimeoutError):
            await client.create_link("Title", ["https://ad.com"], "https://dest.com")

    # 2. Network error
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Network down")):
        with pytest.raises(UnlockifyNetworkError):
            await client.create_link("Title", ["https://ad.com"], "https://dest.com")

    # 3. HTTP 400 Client error
    mock_resp_400 = httpx.Response(
        status_code=400,
        text="Invalid advertisement url",
        request=httpx.Request("POST", "https://api.com"),
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp_400):
        with pytest.raises(UnlockifyRequestRejectedError):
            await client.create_link("Title", ["https://ad.com"], "https://dest.com")

    # 4. HTTP 500 Server error
    mock_resp_500 = httpx.Response(
        status_code=500,
        text="Internal Server Error",
        request=httpx.Request("POST", "https://api.com"),
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp_500):
        with pytest.raises(UnlockifyError):
            await client.create_link("Title", ["https://ad.com"], "https://dest.com")

    # 5. Invalid JSON response
    mock_resp_invalid_json = httpx.Response(
        status_code=200,
        text="<html>Not JSON</html>",
        request=httpx.Request("POST", "https://api.com"),
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp_invalid_json):
        with pytest.raises(UnlockifyInvalidResponseError):
            await client.create_link("Title", ["https://ad.com"], "https://dest.com")


# ---------------------------------------------------------
# 3. PreviewPhotoService Tests
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_preview_photo_service_thumbnail_flow():
    mock_tg = MagicMock()
    mock_tg.get_file = AsyncMock(return_value={"file_path": "thumbnails/thumb123.jpg"})
    mock_tg.download_file = AsyncMock(return_value=b"\xff\xd8\xff\xe0test_jpeg_bytes")
    mock_tg.send_photo = AsyncMock(
        return_value={
            "message_id": 999,
            "photo": [
                {"file_id": "small_id", "width": 100, "height": 100},
                {"file_id": "large_photo_id_777", "width": 800, "height": 800},
            ],
        }
    )
    mock_tg.delete_message = AsyncMock(return_value=True)

    service = PreviewPhotoService(mock_tg)
    photo_file_id = await service.prepare_preview_photo(
        chat_id=12345,
        source_thumbnail_file_id="source_thumb_file_123",
    )

    assert photo_file_id == "large_photo_id_777"
    mock_tg.get_file.assert_called_once_with("source_thumb_file_123")
    mock_tg.download_file.assert_called_once_with("thumbnails/thumb123.jpg")
    mock_tg.send_photo.assert_called_once()
    mock_tg.delete_message.assert_called_once_with(chat_id=12345, message_id=999)


@pytest.mark.asyncio
async def test_preview_photo_service_fallback_to_default():
    mock_tg = MagicMock()
    # No source thumbnail -> uses fallback JPEG
    mock_tg.send_photo = AsyncMock(
        return_value={
            "message_id": 1000,
            "photo": [{"file_id": "fallback_photo_id_888", "width": 1, "height": 1}],
        }
    )
    mock_tg.delete_message = AsyncMock(return_value=True)

    service = PreviewPhotoService(mock_tg)
    photo_file_id = await service.prepare_preview_photo(
        chat_id=12345,
        source_thumbnail_file_id=None,
    )

    assert photo_file_id == "fallback_photo_id_888"
    mock_tg.send_photo.assert_called_once()


@pytest.mark.asyncio
async def test_preview_photo_service_existing_preview_skipped():
    mock_tg = MagicMock()
    service = PreviewPhotoService(mock_tg)
    photo_file_id = await service.prepare_preview_photo(
        chat_id=12345,
        existing_preview_file_id="already_existing_photo_id",
    )
    assert photo_file_id == "already_existing_photo_id"
    mock_tg.send_photo.assert_not_called()


# ---------------------------------------------------------
# 4. VideoProcessingService End-to-End & Checkpointing Tests
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_video_processing_service_full_flow(db_session: AsyncSession):
    # Setup client, bot, sponsor, video
    client = Client(telegram_user_id=201, username="owner201")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=88801,
        username="MediaBot201",
        public_id="bot_201",
        token_encrypted=encrypt_token("123456:BOT_TOKEN_201"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    sponsor = SponsorConfig(
        client_bot_id=bot.id,
        is_enabled=True,
        sponsor_url="https://sponsor.ink/movie-ad",
    )
    db_session.add(sponsor)
    await db_session.flush()

    video_repo = VideoRepository(db_session)
    vid = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="main_video_tg_file_id_999",
        telegram_file_unique_id="main_video_uniq_999",
        source_thumbnail_file_id="source_thumb_id_888",
        caption="Super Fast Action Movie (2026)",
        source_chat_id=201,
    )
    await db_session.commit()

    # Mock Unlockify client
    mock_unlockify = MagicMock(spec=UnlockifyClient)
    mock_unlockify.create_link = AsyncMock(
        return_value=UnlockifyLinkData(
            id="unl_xyz123",
            title="Super Fast Action Movie (2026)",
            ads_count=1,
            unlock_url="https://developer.unlockify.ink/u/unl_xyz123",
        )
    )

    # Mock TelegramClient for thumbnail upload
    mock_tg_resp = {
        "message_id": 55,
        "photo": [{"file_id": "uploaded_preview_photo_id_777", "width": 800, "height": 600}],
    }
    with patch("app.telegram.client.TelegramClient.get_file", new_callable=AsyncMock) as mock_get_file, \
         patch("app.telegram.client.TelegramClient.download_file", new_callable=AsyncMock) as mock_download_file, \
         patch("app.telegram.client.TelegramClient.send_photo", new_callable=AsyncMock) as mock_send_photo, \
         patch("app.telegram.client.TelegramClient.delete_message", new_callable=AsyncMock) as mock_del_msg:

        mock_get_file.return_value = {"file_path": "thumbs/888.jpg"}
        mock_download_file.return_value = b"\xff\xd8\xff\xe0thumb_data"
        mock_send_photo.return_value = mock_tg_resp
        mock_del_msg.return_value = True

        service = VideoProcessingService(
            session=db_session,
            unlockify_client=mock_unlockify,
        )

        res = await service.process_video(vid.id)

        assert res["ok"] is True
        assert res["status"] == "READY"
        assert res["preview_photo_file_id"] == "uploaded_preview_photo_id_777"
        assert res["unlock_url"] == "https://developer.unlockify.ink/u/unl_xyz123"
        assert "broadcast_id" in res

        # Verify Database Video record
        updated_vid = await video_repo.get_by_id(vid.id)
        assert updated_vid.status == VideoStatus.READY
        assert updated_vid.published_at is not None

        # Verify VideoProcessing record
        proc_repo = VideoProcessingRepository(db_session)
        proc = await proc_repo.get_by_video_id(vid.id)
        assert proc.status == ProcessingStatus.READY
        assert proc.thumbnail_file_id == "uploaded_preview_photo_id_777"
        assert proc.unlock_url == "https://developer.unlockify.ink/u/unl_xyz123"
        assert proc.processing_completed_at is not None

        # Verify UnlockLink record
        link_repo = UnlockLinkRepository(db_session)
        link = await link_repo.get_active_by_video(vid.id)
        assert link is not None
        assert link.url == "https://developer.unlockify.ink/u/unl_xyz123"
        assert link.external_reference == "unl_xyz123"
        assert link.status == UnlockLinkStatus.ACTIVE

        # Verify Broadcast record & background job
        broadcast_repo = BroadcastRepository(db_session)
        broadcast = await broadcast_repo.get_by_video_id(vid.id)
        assert broadcast is not None
        assert broadcast.target_type == "ALL_ACTIVE_VIEWERS"

        job_repo = BackgroundJobRepository(db_session)
        jobs, total = await job_repo.list_paginated(job_type=JobType.BROADCAST)
        assert total == 1
        assert jobs[0].broadcast_id == broadcast.id


@pytest.mark.asyncio
async def test_video_processing_service_stage_checkpoints_resume(db_session: AsyncSession):
    """Crash recovery: if preview exists, skips thumbnail; if unlock exists, skips Unlockify."""
    client = Client(telegram_user_id=202, username="owner202")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=88802,
        username="MediaBot202",
        public_id="bot_202",
        token_encrypted=encrypt_token("123456:BOT_TOKEN_202"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    sponsor = SponsorConfig(client_bot_id=bot.id, is_enabled=True, sponsor_url="https://sponsor.ink/ad")
    db_session.add(sponsor)
    await db_session.flush()

    video_repo = VideoRepository(db_session)
    vid = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="vid_file_chk_999",
        telegram_file_unique_id="vid_uniq_chk_999",
        source_chat_id=202,
    )
    proc_repo = VideoProcessingRepository(db_session)
    # Simulate Stage 1 already completed before crash
    await proc_repo.update_progress(
        video_id=vid.id,
        status=ProcessingStatus.PROCESSING_THUMBNAIL,
        thumbnail_file_id="pre_existing_preview_photo_id",
    )
    # Simulate Stage 2 already completed before crash
    await proc_repo.update_progress(
        video_id=vid.id,
        status=ProcessingStatus.CREATING_UNLOCK_LINK,
        unlock_url="https://developer.unlockify.ink/u/saved_url",
    )
    await db_session.commit()

    mock_unlockify = MagicMock(spec=UnlockifyClient)
    service = VideoProcessingService(
        session=db_session,
        unlockify_client=mock_unlockify,
    )

    with patch("app.telegram.client.TelegramClient.send_photo") as mock_send_photo:
        res = await service.process_video(vid.id)

        assert res["ok"] is True
        assert res["status"] == "READY"
        assert res["preview_photo_file_id"] == "pre_existing_preview_photo_id"
        assert res["unlock_url"] == "https://developer.unlockify.ink/u/saved_url"

        # Neither thumbnail upload nor Unlockify call should have occurred
        mock_send_photo.assert_not_called()
        mock_unlockify.create_link.assert_not_called()


@pytest.mark.asyncio
async def test_video_processing_service_missing_sponsor_guard(db_session: AsyncSession):
    """Guards against processing videos when sponsor is disabled or missing."""
    client = Client(telegram_user_id=203, username="owner203")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=88803,
        username="MediaBot203",
        public_id="bot_203",
        token_encrypted=encrypt_token("123456:BOT_TOKEN_203"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    sponsor = SponsorConfig(client_bot_id=bot.id, is_enabled=False, sponsor_url="https://sponsor.ink/ad")
    db_session.add(sponsor)
    await db_session.flush()

    video_repo = VideoRepository(db_session)
    vid = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="vid_file_nosponsor",
        telegram_file_unique_id="vid_uniq_nosponsor",
    )
    await db_session.commit()

    mock_unlockify = MagicMock(spec=UnlockifyClient)
    service = VideoProcessingService(session=db_session, unlockify_client=mock_unlockify)

    res = await service.process_video(vid.id)
    assert res["ok"] is False
    assert res["error"] == "SPONSOR_NOT_CONFIGURED"

    mock_unlockify.create_link.assert_not_called()

    # Video & processing marked FAILED
    updated_vid = await video_repo.get_by_id(vid.id)
    assert updated_vid.status == VideoStatus.FAILED


@pytest.mark.asyncio
async def test_video_processing_service_invalid_bot_token(db_session: AsyncSession):
    """Section 59: When bot token is invalid, marks bot as INVALID_TOKEN and records failure."""
    client = Client(telegram_user_id=204, username="owner204")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=88804,
        username="MediaBot204",
        public_id="bot_204",
        token_encrypted=encrypt_token("invalid:token"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    sponsor = SponsorConfig(client_bot_id=bot.id, is_enabled=True, sponsor_url="https://sponsor.ink/ad")
    db_session.add(sponsor)
    await db_session.flush()

    video_repo = VideoRepository(db_session)
    vid = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="vid_file_invtok",
        telegram_file_unique_id="vid_uniq_invtok",
        source_thumbnail_file_id="thumb_invtok",
    )
    await db_session.commit()

    with patch("app.telegram.client.TelegramClient.get_file", side_effect=TelegramInvalidTokenError("Invalid token")):
        service = VideoProcessingService(session=db_session)
        res = await service.process_video(vid.id)

        assert res["ok"] is False
        assert res["error"] == "INVALID_BOT_TOKEN"

        await db_session.refresh(bot)
        assert bot.status == ClientBotStatus.INVALID_TOKEN


# ---------------------------------------------------------
# 5. VideoProcessingWorker Tests
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_video_processing_worker_job_execution(db_session: AsyncSession):
    client = Client(telegram_user_id=205, username="owner205")
    db_session.add(client)
    await db_session.flush()

    bot = ClientBot(
        client_id=client.id,
        telegram_bot_id=88805,
        username="MediaBot205",
        public_id="bot_205",
        token_encrypted=encrypt_token("123456:BOT_TOKEN_205"),
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    sponsor = SponsorConfig(client_bot_id=bot.id, is_enabled=True, sponsor_url="https://sponsor.ink/ad")
    db_session.add(sponsor)
    await db_session.flush()

    video_repo = VideoRepository(db_session)
    vid = await video_repo.create_video(
        client_bot_id=bot.id,
        telegram_file_id="vid_file_worker",
        telegram_file_unique_id="vid_uniq_worker",
    )

    job_repo = BackgroundJobRepository(db_session)
    job = await job_repo.create_video_processing_job(
        video_id=vid.id,
        client_bot_id=bot.id,
    )
    await db_session.commit()

    mock_service = MagicMock(spec=VideoProcessingService)
    mock_service.process_video = AsyncMock(
        return_value={"ok": True, "video_id": vid.id, "status": "READY", "broadcast_id": 10}
    )

    worker = VideoProcessingWorker(session=db_session, video_processing_service=mock_service)
    pending = await worker.get_pending_jobs()
    assert len(pending) == 1
    assert pending[0].id == job.id

    result = await worker.process_job(job.id)
    assert result["ok"] is True

    await db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.completed_at is not None
