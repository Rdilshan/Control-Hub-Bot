"""Collection draft, publication, and ordered unlock delivery tests."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.enums import ClientBotStatus, JobStatus, JobType
from app.core.enums import ViewerStatus, VideoStatus
from app.core.security import encrypt_token
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.sponsor_config import SponsorConfig
from app.db.models.video import Video
from app.db.models.video_collection import CollectionItemDelivery, VideoCollectionItem
from app.db.models.viewer import Viewer
from app.services.video_collection_service import VideoCollectionService
from app.services.viewer_unlock_service import ViewerUnlockService
from app.workers.collection_delivery import CollectionDeliveryWorker
from app.telegram.errors import TelegramForbiddenError
from app.jobs.recovery import JobRecoveryService
from app.repositories.job import BackgroundJobRepository
from app.telegram.client_bot.dispatcher import ClientBotDispatcher
from app.services.video_processing_service import VideoProcessingService
from app.services.catchup_video_selector_service import CatchupVideoSelectorService
from app.schemas.unlockify import UnlockifyLinkData
from app.db.models.broadcast import Broadcast


async def setup_bot(session):
    owner = Client(telegram_user_id=4455)
    session.add(owner)
    await session.flush()
    bot = ClientBot(
        client_id=owner.id, telegram_bot_id=445500, username="CollectionBot",
        public_id="b_collection", status=ClientBotStatus.ACTIVE,
        token_encrypted=encrypt_token("445500:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"),
    )
    session.add(bot)
    await session.flush()
    session.add(ClientBotAdmin(client_bot_id=bot.id, telegram_user_id=4455, is_active=True))
    session.add(SponsorConfig(client_bot_id=bot.id, is_enabled=True, sponsor_url="https://example.com/unlock"))
    await session.commit()
    return bot


def video_data(number):
    return {
        "chat_id": 4455, "message_id": number, "message_date": 1700000000 + number,
        "video": {"file_id": f"file-{number}", "file_unique_id": f"unique-{number}", "duration": number},
        "caption": f"Part {number}",
    }


@pytest.mark.asyncio
async def test_collection_draft_finishes_as_one_post(db_session):
    bot = await setup_bot(db_session)
    service = VideoCollectionService(db_session)
    draft = await service.start(bot, 4455)
    video_id, reply = await service.finish(bot, 4455)
    assert video_id is None and "at least one" in reply
    for number in range(1, 4):
        await service.receive(bot.id, 4455, video_data(number))
    assert "already received" in await service.receive(bot.id, 4455, video_data(2))
    video_id, reply = await service.finish(bot, 4455)
    assert video_id is None and "thumbnail" in reply
    await service.receive(bot.id, 4455, {"raw_message": {"photo": [{"file_id": "photo-large"}]}, "caption": "My series"})
    video_id, reply = await service.finish(bot, 4455)
    assert video_id is not None and "3 video(s)" in reply
    assert draft.representative_video_id == video_id
    assert (await db_session.get(Video, video_id)).caption == "My series"
    assert (await db_session.get(Video, video_id)).source_sent_at is not None
    assert (await db_session.execute(select(func.count(Video.id)))).scalar_one() == 1
    assert (await db_session.execute(select(func.count(VideoCollectionItem.id)))).scalar_one() == 3
    jobs = list((await db_session.execute(select(BackgroundJob).where(BackgroundJob.job_type == JobType.VIDEO_PROCESS))).scalars())
    assert len(jobs) == 1
    video_id_again, _ = await service.finish(bot, 4455)
    assert video_id_again is None


@pytest.mark.asyncio
async def test_collection_expiry_and_switch_cancel(db_session):
    bot = await setup_bot(db_session)
    service = VideoCollectionService(db_session)
    draft = await service.start(bot, 4455)
    await service.receive(bot.id, 4455, video_data(1))
    assert await service.cancel(bot.id, 4455)
    assert await service.draft(bot.id, 4455) is None
    draft = await service.start(bot, 4455)
    draft.expires_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    assert await service.draft(bot.id, 4455) is None


@pytest.mark.asyncio
async def test_collection_processing_creates_one_live_post_and_one_catchup_item(db_session):
    bot = await setup_bot(db_session)
    service = VideoCollectionService(db_session)
    await service.start(bot, 4455)
    for index in range(1, 4):
        await service.receive(bot.id, 4455, video_data(index))
    await service.receive(bot.id, 4455, {"raw_message": {"photo": [{"file_id": "custom-preview"}]}, "caption": "Series title"})
    video_id, _ = await service.finish(bot, 4455)
    unlockify = AsyncMock()
    unlockify.create_link.return_value = UnlockifyLinkData(id="one-link", unlock_url="https://example.com/one-link")
    result = await VideoProcessingService(db_session, unlockify_client=unlockify).process_video(video_id)
    assert result["ok"]
    assert result["preview_photo_file_id"] == "custom-preview"
    await db_session.commit()
    broadcasts = list((await db_session.execute(select(Broadcast))).scalars())
    assert len(broadcasts) == 1
    assert broadcasts[0].video_id == video_id
    selector = CatchupVideoSelectorService(db_session)
    assert await selector.get_max_ready_video_id(bot.id) == video_id
    assert await selector.count_eligible_unseen_videos(bot.id, viewer_id=999) == 1


@pytest.mark.asyncio
async def test_owner_can_switch_upload_modes_without_losing_saved_video(db_session, monkeypatch, mock_redis_globally):
    bot = await setup_bot(db_session)
    fake = mock_redis_globally
    for path in (
        "app.telegram.client_bot.dispatcher.get_redis",
        "app.telegram.campaign_flow.get_redis",
        "app.telegram.client_bot.admin.custom_messages.get_redis",
        "app.telegram.client_bot.admin.sponsor.get_redis",
    ):
        monkeypatch.setattr(path, lambda: fake)
    monkeypatch.setattr("app.services.video_creation_service.get_redis", lambda: None)
    tg = AsyncMock()
    dispatcher = ClientBotDispatcher(bot, telegram_client=tg)

    async def send(update_id, message_id, **content):
        return await dispatcher.process_update({
            "update_id": update_id,
            "message": {"message_id": message_id, "chat": {"id": 4455, "type": "private"},
                        "from": {"id": 4455}, "date": 1700000000 + message_id, **content},
        }, db_session)

    assert (await send(50001, 1, text="/createvideo"))["action"] == "create_video_prompt_sent"
    assert (await send(50002, 2, video={"file_id": "single", "file_unique_id": "single-unique"}))["action"] == "video_created"
    assert (await send(50003, 3, text="/createcollection"))["action"] == "collection_started"
    assert (await send(50004, 4, video={"file_id": "group-1", "file_unique_id": "group-unique-1"}))["action"] == "collection_input_received"
    assert (await send(50005, 5, photo=[{"file_id": "group-photo"}], caption="Collection title"))["action"] == "collection_input_received"
    assert (await send(50006, 6, text="/done"))["action"] == "collection_published"
    assert (await db_session.execute(select(func.count(Video.id)))).scalar_one() == 2
    assert (await send(50007, 7, text="/createcollection"))["action"] == "collection_started"
    assert (await send(50008, 8, text="/createvideo"))["action"] == "create_video_prompt_sent"
    assert await VideoCollectionService(db_session).draft(bot.id, 4455) is None
    assert (await send(50009, 9, text="/cancel"))["action"] == "create_video_cancelled"


@pytest.mark.asyncio
async def test_collection_unlock_queues_once_and_worker_resumes(db_session, monkeypatch):
    bot = await setup_bot(db_session)
    service = VideoCollectionService(db_session)
    await service.start(bot, 4455)
    await service.receive(bot.id, 4455, video_data(1))
    await service.receive(bot.id, 4455, video_data(2))
    await service.receive(bot.id, 4455, {"raw_message": {"photo": [{"file_id": "photo-large"}]}})
    video_id, _ = await service.finish(bot, 4455)
    video = await db_session.get(Video, video_id)
    from app.core.enums import VideoStatus
    video.status = VideoStatus.READY
    await db_session.commit()

    mock_client = AsyncMock()
    mock_client.send_video.side_effect = [{"message_id": 101}, RuntimeError("temporary")]
    monkeypatch.setattr("app.workers.collection_delivery.TelegramClient", lambda token: mock_client)
    monkeypatch.setattr("app.workers.collection_delivery.telegram_rate_limiter.acquire", AsyncMock())
    unlock_client = AsyncMock()
    unlock = ViewerUnlockService(db_session)
    for _ in range(2):
        result = await unlock.handle_unlock_request(
            bot, 9988, 9988, f"unlock_{video.public_id}", {}, unlock_client,
        )
        assert result["action"] == "collection_delivery_queued"
    jobs = list((await db_session.execute(select(BackgroundJob).where(BackgroundJob.job_type == JobType.COLLECTION_DELIVERY))).scalars())
    assert len(jobs) == 1
    worker = CollectionDeliveryWorker(db_session)
    job = await worker.claim()
    assert job.id == jobs[0].id
    await worker.process(job.id)
    assert job.status == JobStatus.RETRYING
    receipts = list((await db_session.execute(select(CollectionItemDelivery).order_by(CollectionItemDelivery.item_id))).scalars())
    assert [r.status for r in receipts] == ["SENT", "FAILED"]
    job.available_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    mock_client.send_video.side_effect = None
    mock_client.send_video.return_value = {"message_id": 102}
    assert (await worker.claim()).id == job.id
    await worker.process(job.id)
    assert job.status == JobStatus.COMPLETED
    assert mock_client.send_video.await_count == 3


@pytest.mark.asyncio
async def test_stale_collection_job_recovers_and_sends_remaining_video(db_session, monkeypatch):
    bot = await setup_bot(db_session)
    service = VideoCollectionService(db_session)
    draft = await service.start(bot, 4455)
    await service.receive(bot.id, 4455, video_data(1))
    await service.receive(bot.id, 4455, {"raw_message": {"photo": [{"file_id": "cover"}]}})
    video_id, _ = await service.finish(bot, 4455)
    viewer = Viewer(client_bot_id=bot.id, telegram_user_id=9989)
    db_session.add(viewer)
    await db_session.flush()
    job = await BackgroundJobRepository(db_session).create_job(
        job_type=JobType.COLLECTION_DELIVERY,
        payload={"collection_id": draft.id, "viewer_id": viewer.id},
        client_bot_id=bot.id, video_id=video_id, queue_name="collection_delivery",
    )
    await db_session.commit()
    worker = CollectionDeliveryWorker(db_session)
    assert (await worker.claim()).id == job.id
    job.last_heartbeat_at = utc_now() - timedelta(minutes=10)
    await db_session.commit()
    recovered = await JobRecoveryService(db_session).recover_stale_running_jobs(
        threshold_seconds=300, job_type=JobType.COLLECTION_DELIVERY,
    )
    assert [item.id for item in recovered] == [job.id]
    assert job.status == JobStatus.RETRYING
    job.available_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    mock_client = AsyncMock()
    mock_client.send_video.return_value = {"message_id": 201}
    monkeypatch.setattr("app.workers.collection_delivery.TelegramClient", lambda token: mock_client)
    monkeypatch.setattr("app.workers.collection_delivery.telegram_rate_limiter.acquire", AsyncMock())
    assert (await worker.claim()).id == job.id
    await worker.process(job.id)
    assert job.status == JobStatus.COMPLETED
    assert mock_client.send_video.await_count == 1


@pytest.mark.asyncio
async def test_blocked_viewer_can_retry_after_unblocking(db_session, monkeypatch):
    bot = await setup_bot(db_session)
    service = VideoCollectionService(db_session)
    await service.start(bot, 4455)
    await service.receive(bot.id, 4455, video_data(1))
    await service.receive(bot.id, 4455, {"raw_message": {"photo": [{"file_id": "cover"}]}})
    video_id, _ = await service.finish(bot, 4455)
    video = await db_session.get(Video, video_id)
    video.status = VideoStatus.READY
    await db_session.commit()
    unlock = ViewerUnlockService(db_session)
    tg = AsyncMock()
    await unlock.handle_unlock_request(bot, 9988, 9988, f"unlock_{video.public_id}", {}, tg)
    worker = CollectionDeliveryWorker(db_session)
    job = await worker.claim()
    client = AsyncMock()
    client.send_video.side_effect = TelegramForbiddenError()
    monkeypatch.setattr("app.workers.collection_delivery.TelegramClient", lambda token: client)
    monkeypatch.setattr("app.workers.collection_delivery.telegram_rate_limiter.acquire", AsyncMock())
    await worker.process(job.id)
    assert job.status == JobStatus.COMPLETED
    viewer = (await db_session.execute(select(Viewer).where(Viewer.telegram_user_id == 9988))).scalar_one()
    assert viewer.status == ViewerStatus.BLOCKED
    client.send_video.side_effect = None
    client.send_video.return_value = {"message_id": 301}
    await unlock.handle_unlock_request(bot, 9988, 9988, f"unlock_{video.public_id}", {}, tg)
    assert job.status == JobStatus.PENDING
    assert (await worker.claim()).id == job.id
    await worker.process(job.id)
    assert job.status == JobStatus.COMPLETED
