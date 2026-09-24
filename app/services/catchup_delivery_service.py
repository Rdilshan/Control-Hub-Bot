"""Catch-Up Delivery Service for transmitting historical video previews to a single viewer."""

import html
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import CatchupStatus, ClientBotStatus, VideoStatus
from app.core.security import decrypt_bot_token
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.db.models.viewer import Viewer
from app.logging_config import logger
from app.repositories.catchup import CatchupDeliveryRepository
from app.repositories.viewer import ViewerRepository
from app.services.telegram_broadcast_rate_limiter import (
    TelegramBroadcastRateLimiter,
    telegram_rate_limiter,
)
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramForbiddenError, TelegramRateLimitError


class CatchupDeliveryService:
    """Delivers individual historical video previews to a viewer with rate limiting and idempotency."""

    def __init__(
        self,
        session: AsyncSession,
        catchup_delivery_repo: Optional[CatchupDeliveryRepository] = None,
        viewer_repo: Optional[ViewerRepository] = None,
        rate_limiter: Optional[TelegramBroadcastRateLimiter] = None,
    ):
        self.session = session
        self.catchup_delivery_repo = catchup_delivery_repo or CatchupDeliveryRepository(session)
        self.viewer_repo = viewer_repo or ViewerRepository(session)
        self.rate_limiter = rate_limiter or telegram_rate_limiter

    def preflight_delivery(
        self,
        client_bot: ClientBot,
        video: Video,
        video_processing: Optional[Any] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Validates all conditions before sending a historical video preview."""
        if client_bot.status != ClientBotStatus.ACTIVE:
            return False, f"Client bot id={client_bot.id} is not ACTIVE (status={client_bot.status})"

        encrypted_token = getattr(client_bot, "token_encrypted", None) or getattr(
            client_bot, "encrypted_bot_token", None
        )
        if not encrypted_token:
            return False, f"Client bot id={client_bot.id} is missing bot token"

        if video.status != VideoStatus.READY:
            return False, f"Video id={video.id} is not READY (status={video.status})"

        proc = video_processing or getattr(video, "__dict__", {}).get("processing")
        preview_photo_id = (
            getattr(video, "preview_photo_file_id", None)
            or (getattr(proc, "thumbnail_file_id", None) if proc else None)
        )
        if not preview_photo_id:
            return False, f"Video id={video.id} has no preview photo file ID"

        unlock_url = (
            getattr(video, "unlock_url", None)
            or (getattr(proc, "unlock_url", None) if proc else None)
        )
        if not unlock_url:
            return False, f"Video id={video.id} has no unlock URL"

        return True, None

    def build_preview_caption(self, video: Video) -> str:
        """Constructs HTML caption for the preview photo."""
        caption_text = (
            getattr(video, "caption", None)
            or getattr(video, "title", None)
            or getattr(video, "file_name", None)
            or "New Video"
        )
        title = html.escape(caption_text)
        return f"<b>{title}</b>\n\nTap below to unlock and watch."

    def build_inline_keyboard(self, unlock_url: str) -> Dict[str, Any]:
        """Constructs the inline unlock button."""
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "🔓 Unlock Video",
                        "url": unlock_url,
                    }
                ]
            ]
        }

    async def send_catchup_preview_to_viewer(
        self,
        client_bot: ClientBot,
        viewer: Viewer,
        video: Video,
        video_processing: Optional[Any] = None,
        telegram_client: Optional[TelegramClient] = None,
    ) -> Tuple[CatchupStatus, Optional[int], Optional[str], Optional[str]]:
        """Transmits a single historical preview to a viewer.

        Returns:
            Tuple of (status, telegram_message_id, error_code, error_message).
        """
        # 1. Check cross-source duplicate delivery
        has_delivered = await self.catchup_delivery_repo.has_received_video(
            viewer_id=viewer.id,
            video_id=video.id,
        )
        if has_delivered:
            logger.debug("Viewer id=%d already received video id=%d. Skipping.", viewer.id, video.id)
            return CatchupStatus.SKIPPED, None, None, "Already delivered"

        # 2. Resolve video_processing if not provided
        if video_processing is None:
            proc = getattr(video, "__dict__", {}).get("processing")
            if proc is None and getattr(video, "id", None):
                stmt = select(VideoProcessing).where(VideoProcessing.video_id == video.id)
                res = await self.session.execute(stmt)
                video_processing = res.scalar_one_or_none()
            else:
                video_processing = proc

        # 3. Preflight validation
        is_valid, err = self.preflight_delivery(client_bot, video, video_processing)
        if not is_valid:
            logger.error("Catch-up preflight failed for video id=%d, viewer id=%d: %s", video.id, viewer.id, err)
            await self.catchup_delivery_repo.record_delivery(
                client_bot_id=client_bot.id,
                viewer_id=viewer.id,
                video_id=video.id,
                status=CatchupStatus.FAILED,
                error_code="PREFLIGHT_FAILED",
                error_message=err,
            )
            return CatchupStatus.FAILED, None, "PREFLIGHT_FAILED", err

        # 4. Resolve assets & token
        proc = video_processing or getattr(video, "__dict__", {}).get("processing")
        preview_photo_id = (
            getattr(video, "preview_photo_file_id", None)
            or (getattr(proc, "thumbnail_file_id", None) if proc else None)
        )
        unlock_url = (
            getattr(video, "unlock_url", None)
            or (getattr(proc, "unlock_url", None) if proc else None)
        )

        encrypted_token = getattr(client_bot, "token_encrypted", None) or getattr(
            client_bot, "encrypted_bot_token", None
        )
        bot_token = decrypt_bot_token(encrypted_token)

        caption = self.build_preview_caption(video)
        reply_markup = self.build_inline_keyboard(unlock_url)

        # 4. Acquire rate limiter permit
        await self.rate_limiter.acquire(client_bot.id)

        # 5. Send photo via Telegram
        client = telegram_client or TelegramClient(token=bot_token)
        try:
            result = await client.send_photo(
                chat_id=viewer.telegram_user_id,
                photo=preview_photo_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            message_id = result.get("message_id")
            await self.catchup_delivery_repo.record_delivery(
                client_bot_id=client_bot.id,
                viewer_id=viewer.id,
                video_id=video.id,
                status=CatchupStatus.SENT,
                telegram_message_id=message_id,
            )
            return CatchupStatus.SENT, message_id, None, None

        except TelegramForbiddenError as exc:
            logger.warning(
                "Viewer telegram_user_id=%d blocked bot id=%d during catch-up for video id=%d",
                viewer.telegram_user_id,
                client_bot.id,
                video.id,
            )
            await self.viewer_repo.mark_blocked(
                client_bot_id=client_bot.id,
                telegram_user_id=viewer.telegram_user_id,
            )
            await self.catchup_delivery_repo.record_delivery(
                client_bot_id=client_bot.id,
                viewer_id=viewer.id,
                video_id=video.id,
                status=CatchupStatus.BLOCKED,
                error_code="TELEGRAM_FORBIDDEN",
                error_message=str(exc),
            )
            return CatchupStatus.BLOCKED, None, "TELEGRAM_FORBIDDEN", str(exc)

        except TelegramRateLimitError as exc:
            logger.warning(
                "Bot id=%d received 429 during catch-up for video id=%d: retry_after=%s",
                client_bot.id,
                video.id,
                exc.retry_after,
            )
            self.rate_limiter.pause_bot(client_bot.id, exc.retry_after)
            await self.catchup_delivery_repo.record_delivery(
                client_bot_id=client_bot.id,
                viewer_id=viewer.id,
                video_id=video.id,
                status=CatchupStatus.FAILED,
                error_code="RATE_LIMITED",
                error_message=str(exc),
            )
            return CatchupStatus.FAILED, None, "RATE_LIMITED", str(exc)

        except Exception as exc:
            error_code = type(exc).__name__
            logger.error(
                "Failed to send catch-up video id=%d to viewer id=%d: %s",
                video.id,
                viewer.id,
                exc,
            )
            await self.catchup_delivery_repo.record_delivery(
                client_bot_id=client_bot.id,
                viewer_id=viewer.id,
                video_id=video.id,
                status=CatchupStatus.FAILED,
                error_code=error_code,
                error_message=str(exc),
            )
            return CatchupStatus.FAILED, None, error_code, str(exc)
