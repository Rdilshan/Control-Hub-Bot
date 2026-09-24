"""Broadcast Delivery Service for sending preview photos and managing viewer delivery records."""

import html
from typing import Any, Dict, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import ClientBotStatus, DeliveryStatus, VideoStatus
from app.core.security import decrypt_bot_token
from app.db.models.broadcast import Broadcast
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.viewer import Viewer
from app.logging_config import logger
from app.repositories.delivery import BroadcastDeliveryRepository
from app.repositories.viewer import ViewerRepository
from app.services.telegram_broadcast_rate_limiter import (
    TelegramBroadcastRateLimiter,
    telegram_rate_limiter,
)
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramForbiddenError, TelegramRateLimitError


class BroadcastDeliveryService:
    """Manages individual and batched preview delivery to viewers with rate limiting."""

    def __init__(
        self,
        session: AsyncSession,
        delivery_repo: Optional[BroadcastDeliveryRepository] = None,
        viewer_repo: Optional[ViewerRepository] = None,
        rate_limiter: Optional[TelegramBroadcastRateLimiter] = None,
    ):
        self.session = session
        self.delivery_repo = delivery_repo or BroadcastDeliveryRepository(session)
        self.viewer_repo = viewer_repo or ViewerRepository(session)
        self.rate_limiter = rate_limiter or telegram_rate_limiter

    def preflight_broadcast(
        self,
        broadcast: Broadcast,
        video: Video,
        client_bot: ClientBot,
        video_processing: Optional[Any] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Validates all necessary conditions before dispatching a broadcast.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if video.status != VideoStatus.READY:
            return False, f"Video id={video.id} is not READY (status={video.status})"

        proc = video_processing or getattr(video, "__dict__", {}).get("processing")
        preview_photo_id = (
            getattr(video, "preview_photo_file_id", None)
            or (getattr(proc, "thumbnail_file_id", None) if proc else None)
        )
        if not preview_photo_id:
            return False, f"Video id={video.id} has no preview_photo_file_id"

        unlock_url = (
            getattr(video, "unlock_url", None)
            or (getattr(proc, "unlock_url", None) if proc else None)
        )
        if not unlock_url:
            return False, f"Video id={video.id} has no unlock_url"

        if client_bot.status != ClientBotStatus.ACTIVE:
            return False, f"Client bot id={client_bot.id} is not ACTIVE (status={client_bot.status})"

        encrypted_token = getattr(client_bot, "token_encrypted", None) or getattr(
            client_bot, "encrypted_bot_token", None
        )
        if not encrypted_token:
            return False, f"Client bot id={client_bot.id} is missing bot token"

        try:
            token = decrypt_bot_token(encrypted_token)
            if not token:
                return False, f"Client bot id={client_bot.id} has empty decrypted bot token"
        except Exception as exc:
            return False, f"Failed to decrypt bot token: {exc}"

        return True, None

    def build_preview_caption(self, video: Video) -> str:
        """Constructs HTML caption for the preview photo."""
        caption_text = getattr(video, "caption", None) or getattr(video, "title", None) or getattr(video, "file_name", None) or "New Video"
        title = html.escape(caption_text)
        return f"<b>{title}</b>\n\nTap below to unlock and watch."

    def build_inline_keyboard(self, unlock_url: str) -> Dict[str, Any]:
        """Constructs the inline button for Unlockify unlock URL."""
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

    async def send_preview_to_viewer(
        self,
        client_bot_id: int,
        bot_token: str,
        viewer: Viewer,
        broadcast_id: int,
        preview_photo_file_id: str,
        unlock_url: str,
        caption: Optional[str] = None,
        telegram_client: Optional[TelegramClient] = None,
    ) -> Tuple[DeliveryStatus, Optional[int], Optional[str], Optional[str]]:
        """Sends the preview photo to a single viewer and updates delivery records.

        Returns:
            Tuple of (status, telegram_message_id, error_code, error_message).
        """
        # 1. Check existing delivery record for idempotency
        existing_delivery = await self.delivery_repo.get_by_broadcast_and_viewer(
            broadcast_id=broadcast_id,
            viewer_id=viewer.id,
        )
        if existing_delivery and existing_delivery.status == DeliveryStatus.SENT:
            logger.debug(
                "Viewer id=%d already received broadcast id=%d. Skipping.",
                viewer.id,
                broadcast_id,
            )
            return DeliveryStatus.SENT, existing_delivery.telegram_message_id, None, None

        # 2. Acquire rate limiter permit
        await self.rate_limiter.acquire(client_bot_id)

        # 3. Prepare payload
        reply_markup = self.build_inline_keyboard(unlock_url)
        client = telegram_client or TelegramClient(token=bot_token)

        try:
            result = await client.send_photo(
                chat_id=viewer.telegram_user_id,
                photo=preview_photo_file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            message_id = result.get("message_id")
            await self.delivery_repo.record_delivery(
                broadcast_id=broadcast_id,
                viewer_id=viewer.id,
                status=DeliveryStatus.SENT,
                telegram_message_id=message_id,
            )
            return DeliveryStatus.SENT, message_id, None, None

        except TelegramForbiddenError as exc:
            logger.warning(
                "Viewer telegram_user_id=%d blocked bot id=%d during broadcast id=%d",
                viewer.telegram_user_id,
                client_bot_id,
                broadcast_id,
            )
            await self.viewer_repo.mark_blocked(
                client_bot_id=client_bot_id,
                telegram_user_id=viewer.telegram_user_id,
            )
            await self.delivery_repo.record_delivery(
                broadcast_id=broadcast_id,
                viewer_id=viewer.id,
                status=DeliveryStatus.BLOCKED,
                error_code="TELEGRAM_FORBIDDEN",
                error_message=str(exc),
            )
            return DeliveryStatus.BLOCKED, None, "TELEGRAM_FORBIDDEN", str(exc)

        except TelegramRateLimitError as exc:
            logger.warning(
                "Bot id=%d received 429 during broadcast id=%d: retry_after=%s",
                client_bot_id,
                broadcast_id,
                exc.retry_after,
            )
            self.rate_limiter.pause_bot(client_bot_id, exc.retry_after)
            await self.delivery_repo.record_delivery(
                broadcast_id=broadcast_id,
                viewer_id=viewer.id,
                status=DeliveryStatus.FAILED,
                error_code="RATE_LIMITED",
                error_message=str(exc),
            )
            return DeliveryStatus.FAILED, None, "RATE_LIMITED", str(exc)

        except Exception as exc:
            error_code = type(exc).__name__
            logger.error(
                "Failed to send broadcast id=%d to viewer id=%d: %s",
                broadcast_id,
                viewer.id,
                exc,
            )
            await self.delivery_repo.record_delivery(
                broadcast_id=broadcast_id,
                viewer_id=viewer.id,
                status=DeliveryStatus.FAILED,
                error_code=error_code,
                error_message=str(exc),
            )
            return DeliveryStatus.FAILED, None, error_code, str(exc)
