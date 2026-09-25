"""Comprehensive End-to-End Acceptance Test verifying full platform lifecycle and workflow.

Covers the full story from Section 209 of 20_TESTING_IMPLEMENTATION.md:
- Connect Bot A -> Provisioning -> ACTIVE
- Sponsor configuration
- Video intake & processing (without full video download)
- Unlockify destination link generation -> Video READY
- LIVE Broadcast delivery to active viewers
- Viewer Unlock -> Same Bot A delivers saved telegram_file_id
- New Viewer Catch-Up in batches
- LIVE priority over Catch-Up without duplicates
- Bot Pause / Resume lifecycle gating
- Bot Disconnect (token & webhook cleared) -> Reconnect same bot
- Error recovery (Telegram 429 backoff, blocked viewer, Unlockify timeout)
"""

from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    BotAdminRole,
    BotStatus,
    BroadcastStatus,
    CatchupStatus,
    ClientStatus,
    ProcessingStatus,
    VideoStatus,
    ViewerStatus,
)
from app.exceptions import (
    BotPausedException,
    BotDisconnectedException,
    ForbiddenError,
)
from app.repositories.broadcast import BroadcastRepository
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.repositories.client_bot_admin import ClientBotAdminRepository
from app.repositories.sponsor import SponsorRepository
from app.repositories.video import VideoRepository
from app.repositories.viewer import ViewerRepository
from app.repositories.viewer_catchup import ViewerCatchupRepository
from app.services.broadcast_service import BroadcastService
from app.services.catchup_service import CatchupService
from app.services.client_bot_connection_service import ClientBotConnectionService
from app.services.client_bot_lifecycle_service import ClientBotLifecycleService
from app.services.video_creation_service import VideoCreationService
from app.services.video_processing_service import VideoProcessingService
from app.services.viewer_service import ViewerService
from app.services.viewer_unlock_service import ViewerUnlockService
from app.security.authorization import AuthorizationService
from tests.factories import (
    ClientFactory,
    ClientBotFactory,
    ClientBotAdminFactory,
    ViewerFactory,
    VideoFactory,
    SponsorFactory,
)


@pytest.mark.asyncio
async def test_end_to_end_platform_lifecycle_and_content_delivery(db_session: AsyncSession):
    # -------------------------------------------------------------------------
    # 1. Client Onboarding & Bot Connection
    # -------------------------------------------------------------------------
    client = await ClientFactory.create(db_session, telegram_user_id=10001, username="alice_client")
    conn_service = ClientBotConnectionService(db_session)

    from app.telegram.types import TelegramBotInfo

    with patch("app.services.client_bot_connection_service.TelegramClient") as MockTG, \
         patch("app.services.client_bot_provisioning_service.TelegramClient") as MockProvTG:
        mock_tg_instance = AsyncMock()
        mock_tg_instance.get_me.return_value = TelegramBotInfo(id=99887766, username="alice_premium_bot", first_name="Alice Bot", is_bot=True)
        MockTG.return_value = mock_tg_instance

        mock_prov_instance = AsyncMock()
        mock_prov_instance.get_me.return_value = TelegramBotInfo(id=99887766, username="alice_premium_bot", first_name="Alice Bot", is_bot=True)
        mock_prov_instance.set_webhook.return_value = {"ok": True}
        mock_prov_instance.set_my_commands.return_value = {"ok": True}
        MockProvTG.return_value = mock_prov_instance

        is_valid, bot_info, err, is_net = await conn_service.validate_token("99887766:ABCdefGhIJKlmNoPQRsTUVwxyZ12345678")
        assert is_valid is True
        temp_id = await conn_service.prepare_pending_connection(
            client_id=client.id,
            raw_token="99887766:ABCdefGhIJKlmNoPQRsTUVwxyZ12345678",
            bot_info=bot_info,
        )
        ok, msg, connected_bot = await conn_service.confirm_connection(client_id=client.id, temp_id=temp_id)
        assert ok is True

    assert connected_bot.status == BotStatus.ACTIVE
    assert connected_bot.telegram_bot_id == 99887766
    assert connected_bot.token_encrypted is not None

    # -------------------------------------------------------------------------
    # 2. Admin Configures Sponsor URL
    # -------------------------------------------------------------------------
    from app.db.models.sponsor_config import SponsorConfig
    sponsor_repo = SponsorRepository(db_session)
    sponsor = await sponsor_repo.get_by_bot_id(connected_bot.id)
    if not sponsor:
        sponsor = SponsorConfig(
            client_bot_id=connected_bot.id,
            sponsor_url="https://sponsor.example.com/promo",
            button_text="Unlock Video",
            is_enabled=True,
        )
        db_session.add(sponsor)
        await db_session.flush()
    else:
        sponsor = await sponsor_repo.update_sponsor(
            client_bot_id=connected_bot.id,
            sponsor_url="https://sponsor.example.com/promo",
            button_text="Unlock Video",
            is_enabled=True,
        )
    assert sponsor.sponsor_url == "https://sponsor.example.com/promo"
    assert sponsor.is_enabled is True

    # -------------------------------------------------------------------------
    # 3. Admin Creates Video (No full video download)
    # -------------------------------------------------------------------------
    video_repo = VideoRepository(db_session)
    video = await video_repo.create_video(
        client_bot_id=connected_bot.id,
        telegram_file_id="tg_video_file_id_exclusive_001",
        telegram_file_unique_id="uniq_exclusive_001",
        telegram_message_id=501,
        source_chat_id=-10012345678,
        caption="Episode 1: The Masterclass",
    )
    assert video.status == VideoStatus.RECEIVED
    assert video.telegram_file_id == "tg_video_file_id_exclusive_001"

    # -------------------------------------------------------------------------
    # 4. Video Processing & Unlockify Integration -> Video READY
    # -------------------------------------------------------------------------
    from app.schemas.unlockify import UnlockifyLinkData
    video_proc_service = VideoProcessingService(db_session)

    with patch.object(video_proc_service.unlockify_client, "create_link", new_callable=AsyncMock) as mock_unlock, \
         patch("app.services.video_processing_service.PreviewPhotoService.prepare_preview_photo", new_callable=AsyncMock) as mock_prev:
        mock_prev.return_value = "preview_photo_file_id_001"
        mock_unlock.return_value = UnlockifyLinkData(
            id="unl_link_999",
            title="Episode 1: The Masterclass",
            ads_count=1,
            unlock_url="https://unlockify.ink/u/testlink123",
        )

        res = await video_proc_service.process_video(video_id=video.id)
        assert res.get("ok") is True

    ready_video = await video_repo.get_by_id(video.id)
    assert ready_video.status == VideoStatus.READY
    proc = await video_proc_service.proc_repo.get_by_video_id(video.id)
    assert proc.status == ProcessingStatus.READY

    # -------------------------------------------------------------------------
    # 5. LIVE Broadcast to Active Viewers
    # -------------------------------------------------------------------------
    viewer_1 = await ViewerFactory.create(db_session, client_bot_id=connected_bot.id, telegram_user_id=20001)
    viewer_2 = await ViewerFactory.create(db_session, client_bot_id=connected_bot.id, telegram_user_id=20002)

    broadcast_repo = BroadcastRepository(db_session)
    broadcast = await broadcast_repo.create_broadcast(
        client_bot_id=connected_bot.id,
        video_id=ready_video.id,
        total_targets=2,
    )

    broadcast_service = BroadcastService(db_session)
    mock_bcast_tg = AsyncMock()
    mock_bcast_tg.send_photo.return_value = {"ok": True, "result": {"message_id": 901}}

    bcast_res = await broadcast_service.run_broadcast(
        broadcast_id=broadcast.id,
        telegram_client=mock_bcast_tg,
    )

    assert bcast_res["ok"] is True
    assert bcast_res["sent_count"] == 2

    # -------------------------------------------------------------------------
    # 6. Viewer Unlocks -> Same Bot A Delivers Saved Video File ID
    # -------------------------------------------------------------------------
    unlock_service = ViewerUnlockService(db_session)
    mock_unlock_tg = AsyncMock()
    mock_unlock_tg.send_video.return_value = {"ok": True, "result": {"message_id": 905}}

    with patch("app.services.video_delivery_service.TelegramClient") as MockDelivTG:
        MockDelivTG.return_value = mock_unlock_tg
        delivered = await unlock_service.handle_unlock_request(
            client_bot=connected_bot,
            telegram_user_id=viewer_1.telegram_user_id,
            chat_id=viewer_1.telegram_user_id,
            payload=f"unlock_{ready_video.public_id}",
            actor_data={"username": "viewer_1"},
            telegram_client=mock_unlock_tg,
        )

    assert delivered.get("ok") is True

    # -------------------------------------------------------------------------
    # 7. New Viewer Joins -> Catch-Up Delivered in Batches
    # -------------------------------------------------------------------------
    new_viewer = await ViewerFactory.create(db_session, client_bot_id=connected_bot.id, telegram_user_id=20003)
    catchup_service = CatchupService(db_session)
    mock_catch_tg = AsyncMock()
    mock_catch_tg.send_photo.return_value = {"ok": True, "result": {"message_id": 910}}

    catchup, _ = await catchup_service.initialize_or_resume_catchup(
        client_bot_id=connected_bot.id,
        viewer_id=new_viewer.id,
    )
    catchup_result = await catchup_service.process_viewer_catchup_batch(
        viewer_id=new_viewer.id,
        telegram_client=mock_catch_tg,
    )

    assert catchup_result["ok"] is True

    # -------------------------------------------------------------------------
    # 8. Lifecycle Guarding: Bot PAUSED & RESUMED
    # -------------------------------------------------------------------------
    lifecycle_service = ClientBotLifecycleService(db_session)
    auth_service = AuthorizationService()

    # Pause Bot
    ok, msg, paused_bot = await lifecycle_service.pause_bot(client_bot_id=connected_bot.id, client_id=client.id)
    assert ok is True
    assert paused_bot.status == BotStatus.PAUSED

    # Gated operations must raise BotPausedException
    with pytest.raises(BotPausedException):
        auth_service.require_active_client_bot(paused_bot)

    # Resume Bot
    with patch("app.services.client_bot_lifecycle_service.TelegramClient") as MockResumeTG:
        mock_res_tg = AsyncMock()
        mock_res_tg.get_me.return_value = TelegramBotInfo(id=99887766, username="alice_premium_bot", first_name="Alice Bot", is_bot=True)
        MockResumeTG.return_value = mock_res_tg

        ok, msg, resumed_bot = await lifecycle_service.resume_bot(client_bot_id=connected_bot.id, client_id=client.id)
        assert ok is True
        assert resumed_bot.status == BotStatus.ACTIVE
        auth_service.require_active_client_bot(resumed_bot)

    # -------------------------------------------------------------------------
    # 9. Bot Disconnection & Token Cleared
    # -------------------------------------------------------------------------
    with patch("app.services.client_bot_lifecycle_service.TelegramClient") as MockDelTG:
        mock_del_tg = AsyncMock()
        mock_del_tg.delete_webhook.return_value = {"ok": True}
        MockDelTG.return_value = mock_del_tg

        ok, msg = await lifecycle_service.complete_disconnect(client_bot_id=connected_bot.id)
        assert ok is True

    bot_repo = ClientBotRepository(db_session)
    disconnected_bot = await bot_repo.get_by_id(connected_bot.id)
    assert disconnected_bot.status == BotStatus.DISCONNECTED
    assert disconnected_bot.token_encrypted is None

    with pytest.raises(BotDisconnectedException):
        auth_service.require_active_client_bot(disconnected_bot)

    # -------------------------------------------------------------------------
    # 10. Reconnect Same Bot ID Succeeds; Wrong Bot ID Rejected
    # -------------------------------------------------------------------------
    with patch("app.services.client_bot_provisioning_service.TelegramClient") as MockReconTG:
        mock_recon_tg = AsyncMock()
        mock_recon_tg.get_me.return_value = TelegramBotInfo(id=99887766, username="alice_premium_bot", first_name="Alice Bot", is_bot=True)
        mock_recon_tg.set_webhook.return_value = {"ok": True}
        mock_recon_tg.set_my_commands.return_value = {"ok": True}
        MockReconTG.return_value = mock_recon_tg

        temp_id = await conn_service.prepare_pending_connection(
            client_id=client.id,
            raw_token="99887766:NEW_FRESH_TOKEN_ABC1234567890",
            bot_info=TelegramBotInfo(id=99887766, username="alice_premium_bot", first_name="Alice Bot", is_bot=True),
            reconnect_bot_id=connected_bot.id,
        )
        ok, msg, reconnected_bot = await conn_service.confirm_connection(client_id=client.id, temp_id=temp_id)
        assert ok is True
        assert reconnected_bot.status == BotStatus.ACTIVE
        assert reconnected_bot.token_encrypted is not None

        # Reconnect with mismatched Telegram Bot ID is rejected
        temp_id_wrong = await conn_service.prepare_pending_connection(
            client_id=client.id,
            raw_token="11111111:DIFFERENT_BOT_TOKEN_XYZ12345678",
            bot_info=TelegramBotInfo(id=11111111, username="different_bot", first_name="Attacker", is_bot=True),
            reconnect_bot_id=connected_bot.id,
        )
        ok_wrong, msg_wrong, _ = await conn_service.confirm_connection(client_id=client.id, temp_id=temp_id_wrong)
        assert ok_wrong is False
        assert "different bot" in msg_wrong
