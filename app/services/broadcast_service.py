"""Broadcast Service for orchestrating video preview broadcasts and progress tracking."""

from typing import Any, Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.enums import BroadcastStatus, DeliveryStatus
from app.core.security import decrypt_bot_token
from app.core.utils import utc_now
from app.db.models.broadcast import Broadcast
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.logging_config import logger
from app.repositories.broadcast import BroadcastRepository
from app.repositories.delivery import BroadcastDeliveryRepository
from app.repositories.viewer import ViewerRepository
from app.services.broadcast_audience_service import BroadcastAudienceService
from app.services.broadcast_delivery_service import BroadcastDeliveryService
from app.telegram.client import TelegramClient


class BroadcastService:
    """Orchestrates video preview broadcasts to client bot viewers."""

    def __init__(
        self,
        session: AsyncSession,
        broadcast_repo: Optional[BroadcastRepository] = None,
        delivery_repo: Optional[BroadcastDeliveryRepository] = None,
        viewer_repo: Optional[ViewerRepository] = None,
        audience_service: Optional[BroadcastAudienceService] = None,
        delivery_service: Optional[BroadcastDeliveryService] = None,
    ):
        self.session = session
        self.broadcast_repo = broadcast_repo or BroadcastRepository(session)
        self.delivery_repo = delivery_repo or BroadcastDeliveryRepository(session)
        self.viewer_repo = viewer_repo or ViewerRepository(session)
        self.audience_service = audience_service or BroadcastAudienceService(session, self.viewer_repo)
        self.delivery_service = delivery_service or BroadcastDeliveryService(
            session=session,
            delivery_repo=self.delivery_repo,
            viewer_repo=self.viewer_repo,
        )

    async def run_broadcast(
        self,
        broadcast_id: int,
        telegram_client: Optional[TelegramClient] = None,
        batch_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Executes a full or resuming LIVE broadcast run for a given broadcast ID.

        Args:
            broadcast_id: The ID of the Broadcast to execute.
            telegram_client: Optional injected TelegramClient (for tests/custom client).
            batch_size: Database pagination batch size (default from settings).

        Returns:
            Dict containing execution results and status.
        """
        settings = get_settings()
        page_size = batch_size or getattr(settings, "BROADCAST_BATCH_SIZE", 500)

        # 1. Fetch broadcast
        broadcast = await self.broadcast_repo.get_by_id(broadcast_id)
        if not broadcast:
            logger.error("Broadcast id=%d not found", broadcast_id)
            return {"ok": False, "error": "BROADCAST_NOT_FOUND"}

        if broadcast.status in (BroadcastStatus.COMPLETED, BroadcastStatus.CANCELLED):
            logger.info("Broadcast id=%d is already %s. Skipping.", broadcast_id, broadcast.status)
            return {"ok": True, "status": broadcast.status, "message": "Already terminal"}

        # 2. Fetch related Video and ClientBot
        video_stmt = select(Video).where(Video.id == broadcast.video_id)
        video_res = await self.session.execute(video_stmt)
        video = video_res.scalar_one_or_none()

        bot_stmt = select(ClientBot).where(ClientBot.id == broadcast.client_bot_id)
        bot_res = await self.session.execute(bot_stmt)
        client_bot = bot_res.scalar_one_or_none()

        if not video or not client_bot:
            error_msg = f"Missing related entities: video={bool(video)}, client_bot={bool(client_bot)}"
            logger.error(error_msg)
            await self.broadcast_repo.mark_failed(broadcast_id, "MISSING_ENTITIES", error_msg)
            await self.session.commit()
            return {"ok": False, "error": "MISSING_ENTITIES", "message": error_msg}

        # 3. Preflight validation
        proc_stmt = select(VideoProcessing).where(VideoProcessing.video_id == video.id)
        proc_res = await self.session.execute(proc_stmt)
        video_proc = proc_res.scalar_one_or_none()

        is_valid, preflight_error = self.delivery_service.preflight_broadcast(
            broadcast=broadcast,
            video=video,
            client_bot=client_bot,
            video_processing=video_proc,
        )
        if not is_valid:
            logger.error("Broadcast id=%d preflight failed: %s", broadcast_id, preflight_error)
            await self.broadcast_repo.mark_failed(
                broadcast_id,
                "PREFLIGHT_FAILED",
                preflight_error or "Preflight checks failed",
            )
            await self.session.commit()
            return {"ok": False, "error": "PREFLIGHT_FAILED", "message": preflight_error}

        # 4. Set status to RUNNING if not already
        if broadcast.status != BroadcastStatus.RUNNING:
            broadcast.status = BroadcastStatus.RUNNING
            if not broadcast.started_at:
                broadcast.started_at = utc_now()
            await self.session.flush()

        # 5. Initialize snapshot if first start
        if broadcast.audience_max_viewer_id is None:
            total_targets, max_viewer_id = await self.audience_service.capture_audience_snapshot(
                client_bot.id
            )
            broadcast.total_targets = total_targets
            broadcast.audience_max_viewer_id = max_viewer_id
            await self.session.flush()

            if total_targets == 0:
                logger.info("Broadcast id=%d has 0 audience targets. Completing immediately.", broadcast_id)
                await self.broadcast_repo.mark_completed(broadcast_id)
                await self.session.commit()
                return {
                    "ok": True,
                    "broadcast_id": broadcast_id,
                    "status": BroadcastStatus.COMPLETED,
                    "total_targets": 0,
                    "sent_count": 0,
                    "failed_count": 0,
                    "blocked_count": 0,
                }

        await self.session.commit()

        # 6. Decrypt bot token and resolve video assets
        encrypted_token = getattr(client_bot, "token_encrypted", None) or getattr(
            client_bot, "encrypted_bot_token", None
        )
        bot_token = decrypt_bot_token(encrypted_token)

        proc_stmt = select(VideoProcessing).where(VideoProcessing.video_id == video.id)
        proc_res = await self.session.execute(proc_stmt)
        video_proc = proc_res.scalar_one_or_none()

        preview_photo_file_id = (
            getattr(video, "preview_photo_file_id", None)
            or (video_proc.thumbnail_file_id if video_proc else None)
        )
        unlock_url = (
            getattr(video, "unlock_url", None)
            or (video_proc.unlock_url if video_proc else None)
        )

        caption = self.delivery_service.build_preview_caption(video)
        cursor = broadcast.last_processed_viewer_id or 0
        max_id = broadcast.audience_max_viewer_id

        # 7. Keyset pagination loop
        logger.info(
            "Starting broadcast id=%d dispatch: bot_id=%d, cursor=%d, max_id=%s, total_targets=%d",
            broadcast_id,
            client_bot.id,
            cursor,
            max_id,
            broadcast.total_targets,
        )

        while True:
            # Fetch next page of active viewers
            viewers = await self.audience_service.get_next_viewer_page(
                client_bot_id=client_bot.id,
                cursor_id=cursor,
                max_id=max_id,
                limit=page_size,
            )
            if not viewers:
                logger.info("No more viewers to process for broadcast id=%d", broadcast_id)
                break

            sent_delta = 0
            failed_delta = 0
            blocked_delta = 0

            for viewer in viewers:
                status, msg_id, err_code, err_msg = await self.delivery_service.send_preview_to_viewer(
                    client_bot_id=client_bot.id,
                    bot_token=bot_token,
                    viewer=viewer,
                    broadcast_id=broadcast_id,
                    preview_photo_file_id=preview_photo_file_id,
                    unlock_url=unlock_url,
                    caption=caption,
                    telegram_client=telegram_client,
                )

                if status == DeliveryStatus.SENT:
                    sent_delta += 1
                elif status == DeliveryStatus.BLOCKED:
                    blocked_delta += 1
                elif status == DeliveryStatus.FAILED:
                    failed_delta += 1

                cursor = viewer.id

            # Save batch progress and cursor
            await self.broadcast_repo.update_progress_and_cursor(
                broadcast_id=broadcast_id,
                sent_delta=sent_delta,
                failed_delta=failed_delta,
                blocked_delta=blocked_delta,
                last_processed_viewer_id=cursor,
            )
            await self.session.commit()

        # 8. Mark completed
        final_broadcast = await self.broadcast_repo.get_by_id(broadcast_id)
        if final_broadcast and final_broadcast.status == BroadcastStatus.RUNNING:
            await self.broadcast_repo.mark_completed(broadcast_id)
            await self.session.commit()
            final_broadcast = await self.broadcast_repo.get_by_id(broadcast_id)

        logger.info(
            "Broadcast id=%d finished: status=%s, sent=%d, failed=%d, blocked=%d, total=%d",
            broadcast_id,
            final_broadcast.status if final_broadcast else "UNKNOWN",
            final_broadcast.sent_count if final_broadcast else 0,
            final_broadcast.failed_count if final_broadcast else 0,
            final_broadcast.blocked_count if final_broadcast else 0,
            final_broadcast.total_targets if final_broadcast else 0,
        )

        return {
            "ok": True,
            "broadcast_id": broadcast_id,
            "status": final_broadcast.status if final_broadcast else BroadcastStatus.COMPLETED,
            "total_targets": final_broadcast.total_targets if final_broadcast else 0,
            "sent_count": final_broadcast.sent_count if final_broadcast else 0,
            "failed_count": final_broadcast.failed_count if final_broadcast else 0,
            "blocked_count": final_broadcast.blocked_count if final_broadcast else 0,
        }

    async def retry_failed_deliveries(
        self,
        broadcast_id: int,
        telegram_client: Optional[TelegramClient] = None,
        max_attempts: int = 3,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Retries failed deliveries for a broadcast up to max_attempts."""
        broadcast = await self.broadcast_repo.get_by_id(broadcast_id)
        if not broadcast:
            return {"ok": False, "error": "BROADCAST_NOT_FOUND"}

        video_stmt = select(Video).where(Video.id == broadcast.video_id)
        video_res = await self.session.execute(video_stmt)
        video = video_res.scalar_one_or_none()

        bot_stmt = select(ClientBot).where(ClientBot.id == broadcast.client_bot_id)
        bot_res = await self.session.execute(bot_stmt)
        client_bot = bot_res.scalar_one_or_none()

        if not video or not client_bot:
            return {"ok": False, "error": "MISSING_ENTITIES"}

        encrypted_token = getattr(client_bot, "token_encrypted", None) or getattr(
            client_bot, "encrypted_bot_token", None
        )
        bot_token = decrypt_bot_token(encrypted_token)

        proc_stmt = select(VideoProcessing).where(VideoProcessing.video_id == video.id)
        proc_res = await self.session.execute(proc_stmt)
        video_proc = proc_res.scalar_one_or_none()

        preview_photo_file_id = (
            getattr(video, "preview_photo_file_id", None)
            or (video_proc.thumbnail_file_id if video_proc else None)
        )
        unlock_url = (
            getattr(video, "unlock_url", None)
            or (video_proc.unlock_url if video_proc else None)
        )

        caption = self.delivery_service.build_preview_caption(video)

        failed_deliveries = await self.delivery_repo.get_retryable_failed_deliveries(
            broadcast_id=broadcast_id,
            max_attempts=max_attempts,
            limit=limit,
        )

        recovered_count = 0
        still_failed_count = 0

        for delivery in failed_deliveries:
            viewer_stmt = select(Viewer).where(Viewer.id == delivery.viewer_id)
            viewer_res = await self.session.execute(viewer_stmt)
            viewer = viewer_res.scalar_one_or_none()
            if not viewer:
                continue

            status, msg_id, err_code, err_msg = await self.delivery_service.send_preview_to_viewer(
                client_bot_id=client_bot.id,
                bot_token=bot_token,
                viewer=viewer,
                broadcast_id=broadcast_id,
                preview_photo_file_id=preview_photo_file_id,
                unlock_url=unlock_url,
                caption=caption,
                telegram_client=telegram_client,
            )

            if status == DeliveryStatus.SENT:
                recovered_count += 1
                await self.broadcast_repo.update_progress_and_cursor(
                    broadcast_id=broadcast_id,
                    sent_delta=1,
                    failed_delta=-1,
                )
            else:
                still_failed_count += 1

        await self.session.commit()
        return {
            "ok": True,
            "broadcast_id": broadcast_id,
            "retried_count": len(failed_deliveries),
            "recovered_count": recovered_count,
            "still_failed_count": still_failed_count,
        }
