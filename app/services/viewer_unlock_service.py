"""Viewer Unlock Service for processing /start unlock_<video_public_id> requests."""

from typing import Any, Dict, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import ClientBotStatus, JobStatus, JobType, VideoStatus
from app.core.utils import utc_now
from app.db.models.client_bot import ClientBot
from app.db.models.viewer import Viewer
from app.db.models.video_collection import CollectionItemDelivery, VideoCollection, VideoCollectionItem
from app.logging_config import logger
from app.repositories.client_bot import ClientBotRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository
from app.repositories.viewer import ViewerRepository
from app.services.telegram_unlock_destination_service import TelegramUnlockDestinationService
from app.services.video_delivery_service import VideoDeliveryService
from app.telegram.client import TelegramClient


class ViewerUnlockService:
    """Handles viewer return from Unlockify, deep link verification, and video dispatch."""

    def __init__(
        self,
        session: AsyncSession,
        delivery_service: Optional[VideoDeliveryService] = None,
        destination_service: Optional[TelegramUnlockDestinationService] = None,
    ):
        self.session = session
        self.video_repo = VideoRepository(session)
        self.viewer_repo = ViewerRepository(session)
        self.bot_repo = ClientBotRepository(session)
        self.delivery_service = delivery_service or VideoDeliveryService(session)
        self.destination_service = destination_service or TelegramUnlockDestinationService()

    async def handle_unlock_request(
        self,
        client_bot: ClientBot,
        telegram_user_id: int,
        chat_id: int | str,
        payload: str,
        actor_data: Dict[str, Any],
        telegram_client: TelegramClient,
    ) -> Dict[str, Any]:
        """Handles deep-link unlock parameter (/start unlock_<public_id>).

        Args:
            client_bot: Current ClientBot handling the request.
            telegram_user_id: The Telegram user ID of the caller.
            chat_id: The chat ID.
            payload: The /start argument string.
            actor_data: Context information about the user.
            telegram_client: Telegram API client.

        Returns:
            Dict containing processing result.
        """
        # 1. Parse and validate payload
        video_public_id = self.destination_service.parse_payload(payload)
        if not video_public_id:
            logger.warning("Malformed unlock payload received: %s from user=%d", payload, telegram_user_id)
            await telegram_client.send_message(
                chat_id=chat_id,
                text="⚠️ This unlock link is invalid or no longer available.",
            )
            return {"ok": False, "error": "invalid_payload"}

        # 2. Guard: Bot status
        if client_bot.status == ClientBotStatus.PAUSED:
            logger.info("Unlock requested while bot %s is PAUSED", client_bot.username)
            await telegram_client.send_message(
                chat_id=chat_id,
                text="⏸ This bot is temporarily paused.\n\nPlease try again later.",
            )
            return {"ok": False, "error": "bot_paused"}

        if client_bot.status != ClientBotStatus.ACTIVE:
            logger.info("Unlock requested while bot %s has status %s", client_bot.username, client_bot.status)
            await telegram_client.send_message(
                chat_id=chat_id,
                text="⚠️ This service is currently unavailable. Please try again later.",
            )
            return {"ok": False, "error": "bot_inactive"}

        # 3. Look up video strictly scoped by current client_bot_id
        video = await self.video_repo.get_by_public_id_and_bot(
            public_id=video_public_id,
            client_bot_id=client_bot.id,
        )
        if not video:
            logger.warning(
                "Video public_id=%s not found for bot_id=%d (cross-bot or non-existent attempt)",
                video_public_id,
                client_bot.id,
            )
            await telegram_client.send_message(
                chat_id=chat_id,
                text="⚠️ This video is not available.",
            )
            return {"ok": False, "error": "video_not_found"}

        # 4. Guard: Video status
        if video.status == VideoStatus.DISABLED:
            await telegram_client.send_message(
                chat_id=chat_id,
                text="⚠️ This video is no longer available.",
            )
            return {"ok": False, "error": "video_disabled"}

        if video.status != VideoStatus.READY or not video.telegram_file_id:
            await telegram_client.send_message(
                chat_id=chat_id,
                text="⏳ This video is not ready yet.\n\nPlease try again later.",
            )
            return {"ok": False, "error": "video_not_ready"}

        # 5. Resolve or create active Viewer record
        viewer, _ = await self.viewer_repo.get_or_create_viewer(
            client_bot_id=client_bot.id,
            telegram_user_id=telegram_user_id,
            username=actor_data.get("username"),
            first_name=actor_data.get("first_name"),
            last_name=actor_data.get("last_name"),
            language_code=actor_data.get("language_code"),
        )

        collection = (await self.session.execute(select(VideoCollection).where(
            VideoCollection.representative_video_id == video.id,
            VideoCollection.status == "PUBLISHED",
        ))).scalar_one_or_none()
        if collection:
            # Lock the viewer to serialize simultaneous unlock clicks across API workers.
            await self.session.execute(select(Viewer).where(Viewer.id == viewer.id).with_for_update())
            jobs = BackgroundJobRepository(self.session)
            key = f"collection-delivery:{collection.id}:{viewer.id}"
            existing = await jobs.get_by_deduplication_key(key)
            complete = False
            if existing and existing.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                total = (await self.session.execute(select(func.count(VideoCollectionItem.id)).where(
                    VideoCollectionItem.collection_id == collection.id
                ))).scalar_one()
                sent = (await self.session.execute(select(func.count(CollectionItemDelivery.id)).where(
                    CollectionItemDelivery.collection_id == collection.id,
                    CollectionItemDelivery.viewer_id == viewer.id,
                    CollectionItemDelivery.status == "SENT",
                ))).scalar_one()
                complete = sent == total
                if not complete:
                    existing.status = JobStatus.PENDING
                    existing.available_at = utc_now()
                    existing.attempt_count = 0
                    existing.completed_at = None
            if not existing:
                await jobs.create_job(
                    job_type=JobType.COLLECTION_DELIVERY,
                    payload={"collection_id": collection.id, "viewer_id": viewer.id},
                    client_bot_id=client_bot.id, client_id=client_bot.client_id,
                    video_id=video.id, queue_name="collection_delivery",
                    deduplication_key=key, max_attempts=10,
                )
            await self.session.commit()
            reply = "This collection was already sent to you." if complete else "Your collection is being sent. Videos will arrive one by one."
            await telegram_client.send_message(chat_id=chat_id, text=reply)
            return {"ok": True, "action": "collection_delivery_queued", "collection_id": collection.id}

        # 6. Deliver actual video by saved telegram_file_id
        delivery_res = await self.delivery_service.deliver_unlocked_video(
            client_bot=client_bot,
            video=video,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            viewer=viewer,
        )

        return delivery_res
