"""Video Delivery Service for transmitting videos to viewers via Telegram file_id."""

from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import BotEventType, ClientBotStatus, DeliveryStatus
from app.core.security import decrypt_token
from app.db.models.bot_event import BotEvent
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.video_delivery import VideoDelivery
from app.db.models.viewer import Viewer
from app.logging_config import logger
from app.repositories.client_bot import ClientBotRepository
from app.repositories.video_delivery import VideoDeliveryRepository
from app.repositories.viewer import ViewerRepository
from app.telegram.client import TelegramClient
from app.telegram.errors import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramInvalidTokenError,
    TelegramNetworkError,
    TelegramRateLimitError,
)


class VideoDeliveryService:
    """Delivers processed videos to individual viewers by telegram_file_id without VPS downloads."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.delivery_repo = VideoDeliveryRepository(session)
        self.bot_repo = ClientBotRepository(session)
        self.viewer_repo = ViewerRepository(session)

    async def deliver_unlocked_video(
        self,
        client_bot: ClientBot,
        video: Video,
        telegram_user_id: int,
        chat_id: int | str,
        viewer: Optional[Viewer] = None,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Transmits the real Telegram video to a viewer following successful unlock.

        Args:
            client_bot: The ClientBot performing the delivery.
            video: The READY video being delivered.
            telegram_user_id: The recipient Telegram user ID.
            chat_id: The target chat ID.
            viewer: Optional recipient Viewer ORM record.
            caption: Optional caption for the video.

        Returns:
            Dict with delivery result and status.
        """
        # 1. Create delivery record
        delivery = await self.delivery_repo.create_delivery(
            client_bot_id=client_bot.id,
            video_id=video.id,
            viewer_id=viewer.id if viewer else None,
            telegram_user_id=telegram_user_id,
            delivery_type="UNLOCK",
            status=DeliveryStatus.PENDING,
        )

        # 2. Decrypt Client Bot token
        token = decrypt_token(client_bot.token_encrypted)
        telegram_client = TelegramClient(token=token)

        # 3. Determine Caption
        delivery_caption = caption or video.caption or f"🎬 {video.file_name or 'Enjoy your video'}"

        # 4. Attempt delivery via sendVideo with saved telegram_file_id
        try:
            result = await telegram_client.send_video(
                chat_id=chat_id,
                video=video.telegram_file_id,
                caption=delivery_caption,
                duration=video.duration_seconds,
                width=video.width,
                height=video.height,
            )

            msg_id = result.get("message_id")
            await self.delivery_repo.mark_sent(delivery.id, telegram_message_id=msg_id)

            # Record Event
            event = BotEvent(
                client_bot_id=client_bot.id,
                event_type=BotEventType.VIDEO_DELIVERED_AFTER_UNLOCK,
                related_video_id=video.id,
                telegram_user_id=telegram_user_id,
                metadata_json={"delivery_id": delivery.id, "message_id": msg_id},
            )
            self.session.add(event)
            await self.session.flush()

            logger.info(
                "Successfully delivered video id=%d to user=%d via bot=%s",
                video.id,
                telegram_user_id,
                client_bot.username,
            )
            return {
                "ok": True,
                "delivery_id": delivery.id,
                "message_id": msg_id,
                "status": "SENT",
            }

        except TelegramForbiddenError as exc:
            logger.warning("Viewer %d blocked the bot during delivery: %s", telegram_user_id, exc)
            await self.delivery_repo.mark_blocked(delivery.id, error_message=str(exc))
            if viewer:
                await self.viewer_repo.mark_blocked(client_bot.id, telegram_user_id)
            await self.session.flush()
            return {
                "ok": False,
                "error": "TELEGRAM_FORBIDDEN",
                "delivery_id": delivery.id,
                "status": "BLOCKED",
            }

        except TelegramInvalidTokenError as exc:
            logger.error("Client bot %d token invalid during delivery: %s", client_bot.id, exc)
            await self.bot_repo.update_status(client_bot.id, ClientBotStatus.INVALID_TOKEN)
            await self.delivery_repo.mark_failed(delivery.id, "INVALID_BOT_TOKEN", str(exc))
            await self.session.flush()
            return {
                "ok": False,
                "error": "INVALID_BOT_TOKEN",
                "delivery_id": delivery.id,
                "status": "FAILED",
            }

        except TelegramRateLimitError as exc:
            logger.warning("Telegram rate limit during delivery to user %d: %s", telegram_user_id, exc)
            await self.delivery_repo.mark_failed(delivery.id, "TELEGRAM_RATE_LIMIT", str(exc))
            await self.session.flush()
            return {
                "ok": False,
                "error": "TELEGRAM_RATE_LIMIT",
                "retry_after": exc.retry_after,
                "delivery_id": delivery.id,
                "status": "FAILED",
            }

        except TelegramNetworkError as exc:
            logger.error("Network error during delivery to user %d: %s", telegram_user_id, exc)
            await self.delivery_repo.mark_failed(delivery.id, "TELEGRAM_NETWORK_ERROR", str(exc))
            await self.session.flush()
            return {
                "ok": False,
                "error": "TELEGRAM_NETWORK_ERROR",
                "delivery_id": delivery.id,
                "status": "FAILED",
            }

        except TelegramAPIError as exc:
            logger.error("Telegram API error during delivery to user %d: %s", telegram_user_id, exc)
            await self.delivery_repo.mark_failed(delivery.id, "INVALID_FILE_ID", str(exc))
            await self.session.flush()
            return {
                "ok": False,
                "error": "INVALID_FILE_ID",
                "delivery_id": delivery.id,
                "status": "FAILED",
            }

        except Exception as exc:
            logger.exception("Unexpected error delivering video id=%d to user %d: %s", video.id, telegram_user_id, exc)
            await self.delivery_repo.mark_failed(delivery.id, "UNEXPECTED_ERROR", str(exc))
            await self.session.flush()
            return {
                "ok": False,
                "error": "UNEXPECTED_ERROR",
                "delivery_id": delivery.id,
                "status": "FAILED",
            }
