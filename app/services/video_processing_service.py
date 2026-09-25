"""Video Processing Service for orchestrating background video ingest."""

from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import ClientBotStatus, ProcessingStatus, VideoStatus
from app.core.security import decrypt_token
from app.core.utils import utc_now
from app.exceptions import (
    ApplicationError,
    ValidationError,
)
from app.logging_config import logger
from app.telegram.errors import TelegramInvalidTokenError
from app.repositories.client_bot import ClientBotRepository
from app.repositories.sponsor import SponsorRepository
from app.repositories.unlock_link import UnlockLinkRepository
from app.repositories.video import VideoRepository
from app.repositories.video_processing import VideoProcessingRepository
from app.services.broadcast_creation_service import BroadcastCreationService
from app.services.preview_photo_service import PreviewPhotoService
from app.services.telegram_unlock_destination_service import TelegramUnlockDestinationService
from app.services.unlockify_client import UnlockifyClient
from app.services.video_destination_url_service import VideoDestinationUrlService
from app.telegram.client import TelegramClient


class VideoProcessingService:
    """Orchestrates checkpointed, idempotent background processing of ingested videos."""

    def __init__(
        self,
        session: AsyncSession,
        unlockify_client: Optional[UnlockifyClient] = None,
        destination_url_service: Optional[VideoDestinationUrlService] = None,
        telegram_destination_service: Optional[TelegramUnlockDestinationService] = None,
    ):
        self.session = session
        self.video_repo = VideoRepository(session)
        self.proc_repo = VideoProcessingRepository(session)
        self.unlock_link_repo = UnlockLinkRepository(session)
        self.sponsor_repo = SponsorRepository(session)
        self.bot_repo = ClientBotRepository(session)
        self.broadcast_service = BroadcastCreationService(session)
        self.unlockify_client = unlockify_client or UnlockifyClient()
        self.url_service = destination_url_service or VideoDestinationUrlService()
        self.telegram_dest_service = telegram_destination_service or TelegramUnlockDestinationService()

    async def process_video(self, video_id: int) -> Dict[str, Any]:
        """Runs the video processing pipeline for the given video_id.

        Stages:
        1. Preview photo preparation (uses small thumbnail or fallback)
        2. Destination URL generation & Unlockify link creation
        3. READY invariant enforcement & LIVE broadcast scheduling

        Returns:
            Dict indicating execution result and metadata.
        """
        video = await self.video_repo.get_by_id(video_id)
        if not video:
            logger.error("Video id=%d not found for processing", video_id)
            return {"ok": False, "error": "video_not_found"}

        proc = await self.proc_repo.get_by_video_id(video.id)
        if not proc:
            logger.error("VideoProcessing record not found for video_id=%d", video.id)
            return {"ok": False, "error": "processing_record_not_found"}

        client_bot = await self.bot_repo.get_by_id(video.client_bot_id)
        if not client_bot:
            logger.error("ClientBot id=%d not found for video_id=%d", video.client_bot_id, video.id)
            await self.proc_repo.update_progress(
                video_id=video.id,
                status=ProcessingStatus.FAILED,
                error_code="BOT_NOT_FOUND",
                error_message=f"Client bot {video.client_bot_id} does not exist",
            )
            await self.video_repo.update_status(video.id, VideoStatus.FAILED)
            return {"ok": False, "error": "BOT_NOT_FOUND"}

        # If already READY and has LIVE broadcast, idempotently complete
        if video.status == VideoStatus.READY and proc.status == ProcessingStatus.READY:
            logger.info("Video id=%d already READY. Ensuring LIVE broadcast exists.", video.id)
            broadcast = await self.broadcast_service.create_live_broadcast(video=video, client_bot=client_bot)
            return {"ok": True, "video_id": video.id, "status": "READY", "broadcast_id": broadcast.id}

        # 1. Guard: Check Sponsor Configuration
        sponsor_config = await self.sponsor_repo.get_by_bot_id(client_bot.id)
        if not sponsor_config or not sponsor_config.is_enabled or not sponsor_config.sponsor_url:
            error_msg = "Sponsor URL is not configured or is disabled for this bot"
            logger.warning("Video processing failed: %s (bot_id=%d)", error_msg, client_bot.id)
            await self.proc_repo.update_progress(
                video_id=video.id,
                status=ProcessingStatus.FAILED,
                error_code="SPONSOR_NOT_CONFIGURED",
                error_message=error_msg,
            )
            await self.video_repo.update_status(video.id, VideoStatus.FAILED)
            return {"ok": False, "error": "SPONSOR_NOT_CONFIGURED", "message": error_msg}

        try:
            # Decrypt Bot Token for Telegram operations
            decrypted_token = decrypt_token(client_bot.token_encrypted)
            telegram_client = TelegramClient(token=decrypted_token)

            # STAGE 1: Prepare Preview Photo
            preview_photo_file_id = None
            if proc.thumbnail_file_id and proc.status in (ProcessingStatus.CREATING_UNLOCK_LINK, ProcessingStatus.READY):
                preview_photo_file_id = proc.thumbnail_file_id
            elif (
                proc.thumbnail_file_id
                and proc.status == ProcessingStatus.PROCESSING_THUMBNAIL
                and proc.thumbnail_file_id != video.source_thumbnail_file_id
            ):
                preview_photo_file_id = proc.thumbnail_file_id

            if not preview_photo_file_id:
                await self.proc_repo.update_progress(video_id=video.id, status=ProcessingStatus.PROCESSING_THUMBNAIL)
                await self.video_repo.update_status(video.id, VideoStatus.PROCESSING)
                preview_service = PreviewPhotoService(telegram_client)
                upload_chat_id = video.source_chat_id or client_bot.telegram_bot_id
                preview_photo_file_id = await preview_service.prepare_preview_photo(
                    chat_id=upload_chat_id,
                    source_thumbnail_file_id=video.source_thumbnail_file_id,
                )
                await self.proc_repo.update_progress(
                    video_id=video.id,
                    status=ProcessingStatus.PROCESSING_THUMBNAIL,
                    thumbnail_file_id=preview_photo_file_id,
                )

            # STAGE 2: Create Destination URL and Unlockify Link
            await self.proc_repo.update_progress(video_id=video.id, status=ProcessingStatus.CREATING_UNLOCK_LINK)

            active_unlock_link = await self.unlock_link_repo.get_active_by_video(video.id)
            if active_unlock_link and active_unlock_link.url:
                unlock_url = active_unlock_link.url
                await self.proc_repo.update_progress(
                    video_id=video.id,
                    status=ProcessingStatus.CREATING_UNLOCK_LINK,
                    unlock_url=unlock_url,
                )
            elif proc.unlock_url:
                unlock_url = proc.unlock_url
            else:
                raw_title = video.caption or video.file_name or f"Video {video.public_id}"
                clean_title = " ".join(raw_title.strip().split())
                if len(clean_title) > 80:
                    clean_title = clean_title[:80].strip()

                bot_username = client_bot.username
                if not bot_username:
                    try:
                        bot_info = await telegram_client.get_me()
                        bot_username = bot_info.get("username")
                    except Exception as me_err:
                        logger.warning("Failed to fetch get_me for client_bot id=%d: %s", client_bot.id, me_err)

                if bot_username:
                    destination_url = self.telegram_dest_service.build_destination(
                        bot_username=bot_username,
                        video_public_id=video.public_id,
                    )
                else:
                    destination_url = self.url_service.build_destination_url(video.public_id)

                try:
                    link_data = await self.unlockify_client.create_link(
                        title=clean_title,
                        advertisement_urls=[sponsor_config.sponsor_url],
                        destination_url=destination_url,
                    )
                    unlock_url = link_data.unlock_url
                    link_id = link_data.id
                    provider = "unlockify"
                except Exception as unlockify_err:
                    logger.warning(
                        "Unlockify API call failed (%s). Falling back to direct sponsor link.",
                        unlockify_err,
                    )
                    unlock_url = sponsor_config.sponsor_url
                    link_id = None
                    provider = "direct_sponsor"

                await self.unlock_link_repo.create(
                    video_id=video.id,
                    client_bot_id=client_bot.id,
                    url=unlock_url,
                    provider=provider,
                    external_reference=link_id,
                )
                await self.proc_repo.update_progress(
                    video_id=video.id,
                    status=ProcessingStatus.CREATING_UNLOCK_LINK,
                    unlock_url=unlock_url,
                )

            # STAGE 3: Invariant Verification, Mark READY, and Queue Broadcast
            if not (video.telegram_file_id and preview_photo_file_id and unlock_url):
                raise ValidationError("Invariants for READY video not met: missing required file_id or unlock_url")

            await self.proc_repo.update_progress(
                video_id=video.id,
                status=ProcessingStatus.READY,
                thumbnail_file_id=preview_photo_file_id,
                unlock_url=unlock_url,
            )
            await self.video_repo.mark_ready(video_id=video.id, client_bot_id=client_bot.id)

            broadcast = await self.broadcast_service.create_live_broadcast(video=video, client_bot=client_bot)

            logger.info("Video id=%d processing complete and marked READY", video.id)
            return {
                "ok": True,
                "video_id": video.id,
                "status": "READY",
                "preview_photo_file_id": preview_photo_file_id,
                "unlock_url": unlock_url,
                "broadcast_id": broadcast.id,
            }

        except TelegramInvalidTokenError as exc:
            logger.error("Invalid bot token encountered while processing video id=%d: %s", video.id, exc)
            await self.bot_repo.update_status(client_bot.id, ClientBotStatus.INVALID_TOKEN)
            await self.proc_repo.update_progress(
                video_id=video.id,
                status=ProcessingStatus.FAILED,
                error_code="INVALID_BOT_TOKEN",
                error_message=str(exc),
            )
            await self.video_repo.update_status(video.id, VideoStatus.FAILED)
            return {"ok": False, "error": "INVALID_BOT_TOKEN", "message": str(exc)}

        except Exception as exc:
            err_code = getattr(exc, "code", "PROCESSING_FAILED")
            err_msg = str(exc)
            logger.error("Error processing video id=%d: %s (code=%s)", video.id, err_msg, err_code)
            await self.proc_repo.increment_retry(video.id)
            await self.proc_repo.update_progress(
                video_id=video.id,
                status=ProcessingStatus.FAILED,
                error_code=err_code,
                error_message=err_msg,
            )
            await self.video_repo.update_status(video.id, VideoStatus.FAILED)
            return {"ok": False, "error": err_code, "message": err_msg}
