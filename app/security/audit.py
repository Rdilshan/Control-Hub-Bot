"""Security and operational audit logging service storing append-only events."""

from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import BotEventType
from app.repositories.event import BotEventRepository


class SecurityAuditService:
    """Service providing persistent, append-only security audit event logging."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = BotEventRepository(session)

    async def log_event(
        self,
        client_bot_id: int,
        event_type: BotEventType,
        telegram_user_id: Optional[int] = None,
        related_video_id: Optional[int] = None,
        related_broadcast_id: Optional[int] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
    ):
        """Records an immutable security/lifecycle audit event."""
        return await self.repo.record_event(
            client_bot_id=client_bot_id,
            event_type=event_type,
            telegram_user_id=telegram_user_id,
            related_video_id=related_video_id,
            related_broadcast_id=related_broadcast_id,
            metadata_json=metadata_json,
        )

    async def log_bot_connected(self, client_bot_id: int, telegram_user_id: Optional[int] = None, bot_username: Optional[str] = None):
        return await self.log_event(
            client_bot_id=client_bot_id,
            event_type=BotEventType.BOT_CONNECTED,
            telegram_user_id=telegram_user_id,
            metadata_json={"username": bot_username} if bot_username else {},
        )

    async def log_bot_paused(self, client_bot_id: int, telegram_user_id: Optional[int] = None, reason: Optional[str] = None):
        return await self.log_event(
            client_bot_id=client_bot_id,
            event_type=BotEventType.BOT_PAUSED,
            telegram_user_id=telegram_user_id,
            metadata_json={"reason": reason} if reason else {},
        )

    async def log_bot_resumed(self, client_bot_id: int, telegram_user_id: Optional[int] = None):
        return await self.log_event(
            client_bot_id=client_bot_id,
            event_type=BotEventType.BOT_RESUMED,
            telegram_user_id=telegram_user_id,
        )

    async def log_bot_disconnected(self, client_bot_id: int, telegram_user_id: Optional[int] = None):
        return await self.log_event(
            client_bot_id=client_bot_id,
            event_type=BotEventType.BOT_DISCONNECTED,
            telegram_user_id=telegram_user_id,
        )

    async def log_bot_reconnected(self, client_bot_id: int, telegram_user_id: Optional[int] = None):
        return await self.log_event(
            client_bot_id=client_bot_id,
            event_type=BotEventType.BOT_RECONNECTED,
            telegram_user_id=telegram_user_id,
        )

    async def log_sponsor_changed(self, client_bot_id: int, telegram_user_id: Optional[int] = None, sponsor_id: Optional[int] = None):
        return await self.log_event(
            client_bot_id=client_bot_id,
            event_type=BotEventType.SPONSOR_CHANGED,
            telegram_user_id=telegram_user_id,
            metadata_json={"sponsor_id": sponsor_id} if sponsor_id else {},
        )

    async def log_start_message_changed(self, client_bot_id: int, telegram_user_id: Optional[int] = None):
        return await self.log_event(
            client_bot_id=client_bot_id,
            event_type=BotEventType.START_MESSAGE_CHANGED,
            telegram_user_id=telegram_user_id,
        )

    async def log_default_message_changed(self, client_bot_id: int, telegram_user_id: Optional[int] = None):
        return await self.log_event(
            client_bot_id=client_bot_id,
            event_type=BotEventType.DEFAULT_MESSAGE_CHANGED,
            telegram_user_id=telegram_user_id,
        )

    async def log_manual_retry(self, client_bot_id: int, telegram_user_id: Optional[int] = None, job_id: Optional[int] = None):
        return await self.log_event(
            client_bot_id=client_bot_id,
            event_type=BotEventType.JOB_MANUAL_RETRY,
            telegram_user_id=telegram_user_id,
            metadata_json={"job_id": job_id} if job_id else {},
        )
