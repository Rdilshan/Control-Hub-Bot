"""Custom campaign delivery across client bots and Control Hub recipients."""

from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select
from app.core.enums import ClientBotStatus, ClientStatus, ViewerStatus
from app.core.security import encrypt_token
from app.db.models.broadcast import Broadcast
from app.db.models.broadcast_delivery import BroadcastDelivery
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.viewer import Viewer
from app.db.models.platform_owner import PlatformOwner
from app.services.broadcast_service import BroadcastService
from app.services.message_campaign_service import MessageCampaignService
from app.services.message_content import MAX_CROSS_BOT_BYTES, extract_content, validate_cross_bot_content
from app.workers.owner_message_campaign import OwnerMessageCampaignWorker
from app.repositories.job import BackgroundJobRepository
from app.telegram.errors import TelegramForbiddenError
from app.telegram.control_hub import campaigns as hub_campaigns
from app.telegram.client_bot.admin.campaigns import owner_allowed
from app.telegram.client_bot.admin import campaigns as client_campaigns
from app.db.models.client_bot_admin import ClientBotAdmin
from app.core.enums import BotAdminRole
from app.telegram.campaign_flow import get_draft
from app.services.catchup_scheduler_service import CatchupSchedulerService


async def add_bot(session, user_id, bot_id):
    owner = Client(telegram_user_id=user_id, status=ClientStatus.ACTIVE)
    session.add(owner)
    await session.flush()
    bot = ClientBot(
        client_id=owner.id, telegram_bot_id=bot_id, username=f"bot{bot_id}",
        token_encrypted=encrypt_token("123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"),
        status=ClientBotStatus.ACTIVE,
    )
    session.add(bot)
    await session.flush()
    return owner, bot


@pytest.mark.asyncio
async def test_all_bot_text_campaign_delivers_and_aggregates(db_session):
    _, bot_a = await add_bot(db_session, 501, 10001)
    _, bot_b = await add_bot(db_session, 502, 10002)
    for bot, user in ((bot_a, 701), (bot_b, 702)):
        db_session.add(Viewer(client_bot_id=bot.id, telegram_user_id=user, status=ViewerStatus.ACTIVE))
    await db_session.flush()
    service = MessageCampaignService(db_session)
    campaign = await service.create(creator_telegram_user_id=900, audience="ALL_VIEWERS", content={"kind": "text", "text": "Hello", "entities": []}, source_bot="HUB")
    await db_session.commit()
    broadcasts = list((await db_session.execute(select(Broadcast).where(Broadcast.campaign_id == campaign.id))).scalars())
    assert len(broadcasts) == 2
    tg = AsyncMock()
    tg.send_content.side_effect = [{"message_id": 11}, {"message_id": 12}]
    for broadcast in broadcasts:
        result = await BroadcastService(db_session).run_broadcast(broadcast.id, telegram_client=tg)
        assert result["sent_count"] == 1
    detail = await service.detail(campaign.id)
    assert (detail["total"], detail["sent"], detail["remaining"]) == (2, 2, 0)
    assert len(list((await db_session.execute(select(BroadcastDelivery))).scalars())) == 2


@pytest.mark.asyncio
async def test_waiting_jobs_for_busy_bot_do_not_hide_other_bot(db_session):
    _, bot_a = await add_bot(db_session, 501, 10001)
    _, bot_b = await add_bot(db_session, 502, 10002)
    service = MessageCampaignService(db_session)
    for index in range(8):
        await service.create(501, "ONE_BOT", {"kind": "text", "text": f"A{index}"}, "CLIENT", bot_a.id)
    await service.create(502, "ONE_BOT", {"kind": "text", "text": "B"}, "CLIENT", bot_b.id)
    await db_session.commit()
    jobs = await BackgroundJobRepository(db_session).claim_runnable_broadcast_jobs(limit=1)
    assert len(jobs) == 1 and jobs[0].client_bot_id == bot_a.id
    await db_session.commit()
    jobs = await BackgroundJobRepository(db_session).claim_runnable_broadcast_jobs(limit=1)
    assert len(jobs) == 1 and jobs[0].client_bot_id == bot_b.id


@pytest.mark.asyncio
async def test_repeated_confirmation_does_not_create_second_campaign(db_session):
    _, bot = await add_bot(db_session, 501, 10001)
    service = MessageCampaignService(db_session)
    first = await service.create(501, "ONE_BOT", {"kind": "text", "text": "Hello"}, "CLIENT", bot.id, idempotency_key="client:1:501:42")
    second = await service.create(501, "ONE_BOT", {"kind": "text", "text": "Hello"}, "CLIENT", bot.id, idempotency_key="client:1:501:42")
    assert first.id == second.id
    assert len(list((await db_session.execute(select(Broadcast))).scalars())) == 1


@pytest.mark.asyncio
async def test_client_owner_compose_confirm_and_live_priority(db_session, mock_redis_globally):
    _, bot = await add_bot(db_session, 501, 10001)
    tg = AsyncMock()
    with patch("app.telegram.campaign_flow.get_redis", return_value=mock_redis_globally):
        await client_campaigns.start(bot.id, 501, 501, tg, db_session)
        await client_campaigns.receive(bot.id, 501, 501, {"message_id": 77, "text": "Update"}, tg)
        assert (await get_draft(str(bot.id), 501))["content"]["text"] == "Update"
        result = await client_campaigns.callback(bot.id, 501, 501, "admin:campaign:confirm", tg, db_session)
    assert result["action"] == "campaign_created"
    assert await CatchupSchedulerService(db_session).has_live_broadcast_in_progress(bot.id)


@pytest.mark.asyncio
async def test_owner_campaign_sends_only_active_clients(db_session):
    await add_bot(db_session, 501, 10001)
    inactive = Client(telegram_user_id=503, status=ClientStatus.SUSPENDED)
    db_session.add(inactive)
    await db_session.flush()
    campaign = await MessageCampaignService(db_session).create(900, "OWNERS", {"kind": "text", "text": "News", "entities": []}, "HUB")
    await db_session.commit()
    worker = OwnerMessageCampaignWorker(db_session)
    job = await worker.claim_job()
    tg = AsyncMock()
    tg.send_content.return_value = {"message_id": 88}
    await worker.process_job(job.id, tg)
    assert tg.send_content.await_count == 1
    assert (await MessageCampaignService(db_session).detail(campaign.id))["sent"] == 1


@pytest.mark.asyncio
async def test_only_one_control_hub_campaign_claims_at_a_time(db_session):
    db_session.add(PlatformOwner(telegram_user_id=900, is_active=True))
    await db_session.flush()
    service = MessageCampaignService(db_session)
    await service.create(900, "OWNERS", {"kind": "text", "text": "First"}, "HUB")
    await service.create(900, "OWNERS", {"kind": "text", "text": "Second"}, "HUB")
    await db_session.commit()
    worker = OwnerMessageCampaignWorker(db_session)
    first = await worker.claim_job()
    assert first is not None
    assert await worker.claim_job() is None


@pytest.mark.asyncio
async def test_owner_failed_delivery_is_retried(db_session):
    await add_bot(db_session, 501, 10001)
    campaign = await MessageCampaignService(db_session).create(900, "OWNERS", {"kind": "text", "text": "News", "entities": []}, "HUB")
    await db_session.commit()
    worker = OwnerMessageCampaignWorker(db_session)
    job = await worker.claim_job()
    tg = AsyncMock()
    tg.send_content.side_effect = [RuntimeError("temporary"), {"message_id": 88}]
    await worker.process_job(job.id, tg)
    detail = await MessageCampaignService(db_session).detail(campaign.id)
    assert (detail["sent"], detail["failed"], detail["status"]) == (1, 0, "COMPLETED")


@pytest.mark.asyncio
async def test_client_campaign_permission_is_owner_only(db_session):
    _, bot = await add_bot(db_session, 501, 10001)
    owner = ClientBotAdmin(client_bot_id=bot.id, telegram_user_id=501, role=BotAdminRole.OWNER, is_active=True)
    admin = ClientBotAdmin(client_bot_id=bot.id, telegram_user_id=502, role=BotAdminRole.ADMIN, is_active=True)
    db_session.add_all([owner, admin])
    await db_session.flush()
    assert await owner_allowed(db_session, owner.id, bot.id)
    assert not await owner_allowed(db_session, admin.id, bot.id)


@pytest.mark.asyncio
async def test_hub_rejects_large_media_before_confirmation(mock_redis_globally):
    with patch("app.telegram.campaign_flow.get_redis", return_value=mock_redis_globally):
        await hub_campaigns.callback(900, 900, "owner:campaign:all", AsyncMock(), None)
        tg = AsyncMock()
        tg.get_file.return_value = {"file_size": MAX_CROSS_BOT_BYTES + 1, "file_path": "large.mp4"}
        result = await hub_campaigns.receive(900, 900, {"video": {"file_id": "large", "file_size": MAX_CROSS_BOT_BYTES + 1}}, tg)
        assert result["action"] == "campaign_unsupported"
        assert not (await get_draft("hub", 900)).get("content")
        tg.send_content.assert_not_called()


@pytest.mark.asyncio
async def test_cross_bot_media_is_staged_once(db_session):
    _, bot = await add_bot(db_session, 501, 10001)
    for user in (701, 702):
        db_session.add(Viewer(client_bot_id=bot.id, telegram_user_id=user, status=ViewerStatus.ACTIVE))
    await db_session.flush()
    content = {"kind": "photo", "file_id": "hub-photo", "file_size": 10, "file_name": "p.jpg", "mime_type": "image/jpeg", "caption": "Hi", "caption_entities": []}
    campaign = await MessageCampaignService(db_session).create(900, "ONE_BOT", content, "HUB", bot.id)
    await db_session.commit()
    broadcast = (await db_session.execute(select(Broadcast).where(Broadcast.campaign_id == campaign.id))).scalar_one()
    tg = AsyncMock()
    tg.send_content.side_effect = [
        {"message_id": 1, "photo": [{"file_id": "bot-photo"}]},
        {"message_id": 2, "photo": [{"file_id": "bot-photo"}]},
    ]
    with patch("app.services.broadcast_service.TelegramClient") as source_cls:
        source = source_cls.return_value
        source.get_file = AsyncMock(return_value={"file_path": "p.jpg", "file_size": 10})
        source.download_file = AsyncMock(return_value=b"abc")
        await BroadcastService(db_session).run_broadcast(broadcast.id, telegram_client=tg)
    source.download_file.assert_awaited_once()
    assert tg.send_content.await_args_list[0].kwargs["file_bytes"] == b"abc"
    assert tg.send_content.await_args_list[1].kwargs["file_id"] == "bot-photo"


@pytest.mark.asyncio
async def test_blocked_first_recipient_does_not_redownload_media(db_session):
    _, bot = await add_bot(db_session, 501, 10001)
    for user in (701, 702):
        db_session.add(Viewer(client_bot_id=bot.id, telegram_user_id=user, status=ViewerStatus.ACTIVE))
    await db_session.flush()
    content = {"kind": "photo", "file_id": "hub-photo", "file_size": 10, "file_name": "p.jpg", "mime_type": "image/jpeg"}
    campaign = await MessageCampaignService(db_session).create(900, "ONE_BOT", content, "HUB", bot.id)
    await db_session.commit()
    broadcast = (await db_session.execute(select(Broadcast).where(Broadcast.campaign_id == campaign.id))).scalar_one()
    tg = AsyncMock()
    tg.send_content.side_effect = [TelegramForbiddenError(), {"message_id": 2, "photo": [{"file_id": "bot-photo"}]}]
    with patch("app.services.broadcast_service.TelegramClient") as source_cls:
        source = source_cls.return_value
        source.get_file = AsyncMock(return_value={"file_path": "p.jpg", "file_size": 10})
        source.download_file = AsyncMock(return_value=b"abc")
        result = await BroadcastService(db_session).run_broadcast(broadcast.id, telegram_client=tg)
    source.download_file.assert_awaited_once()
    assert result["blocked_count"] == 1
    assert result["sent_count"] == 1


def test_supported_content_and_cross_bot_limit():
    assert extract_content({"photo": [{"file_id": "p", "file_size": 12}], "caption": "Hi"})["kind"] == "photo"
    for kind in ("video", "audio", "voice", "document", "animation", "sticker"):
        assert extract_content({kind: {"file_id": "f"}})["kind"] == kind
    with pytest.raises(ValueError):
        extract_content({"poll": {"question": "A?"}})
    with pytest.raises(ValueError):
        validate_cross_bot_content({"kind": "video", "file_size": MAX_CROSS_BOT_BYTES + 1})
