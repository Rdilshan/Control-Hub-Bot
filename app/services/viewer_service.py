"""Viewer Service managing normal subscriber journeys, profile syncing, and catch-up eligibility."""

from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    BotEventType,
    CatchupStatus,
    ClientBotStatus,
    JobStatus,
    JobType,
    ViewerStatus,
    enum_val,
)
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_settings import ClientBotSettings
from app.db.models.viewer import Viewer
from app.logging_config import get_logger
from app.repositories.catchup import CatchupDeliveryRepository
from app.repositories.event import BotEventRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository
from app.repositories.viewer import ViewerRepository
from app.services.catchup_service import CatchupService
from app.telegram.client import TelegramClient
from app.telegram.client_bot import messages

logger = get_logger(__name__)


class ViewerService:
    """Domain service managing Viewer registration, communication, and historical catch-up queuing."""

    def __init__(
        self,
        session: AsyncSession,
        catchup_service: Optional[CatchupService] = None,
    ):
        self.session = session
        self.viewer_repo = ViewerRepository(session)
        self.video_repo = VideoRepository(session)
        self.catchup_repo = CatchupDeliveryRepository(session)
        self.job_repo = BackgroundJobRepository(session)
        self.event_repo = BotEventRepository(session)
        self.catchup_service = catchup_service or CatchupService(session)

    async def get_bot_settings(self, client_bot_id: int) -> Optional[ClientBotSettings]:
        """Retrieves configured messages for a Client Bot."""
        stmt = select(ClientBotSettings).where(ClientBotSettings.client_bot_id == client_bot_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def handle_viewer_start(
        self,
        client_bot: ClientBot,
        telegram_user_id: int,
        chat_id: int,
        telegram_client: TelegramClient,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Handles /start command for a normal viewer."""
        # 1. Check Bot status
        raw_status = enum_val(client_bot.status)
        if raw_status == ClientBotStatus.PAUSED.value:
            await telegram_client.send_message(
                chat_id=chat_id,
                text=messages.bot_paused_viewer_message(),
            )
            return {"ok": True, "action": "bot_paused"}

        if raw_status != ClientBotStatus.ACTIVE.value:
            await telegram_client.send_message(
                chat_id=chat_id,
                text=messages.bot_inactive_message(),
            )
            return {"ok": True, "action": "bot_inactive"}

        # 2. Get or Create Viewer (re-activates if previously blocked)
        viewer, is_new = await self.viewer_repo.get_or_create_viewer(
            client_bot_id=client_bot.id,
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
        )

        # 3. Load custom start message
        settings = await self.get_bot_settings(client_bot.id)
        start_text = settings.start_message if settings and settings.start_message else None

        await telegram_client.send_message(
            chat_id=chat_id,
            text=messages.viewer_welcome_message(
                custom_start_message=start_text,
                bot_username=client_bot.username,
            ),
        )

        # 4. Check historical video catch-up eligibility and queue if needed
        catchup_queued = await self.check_and_enqueue_catchup(
            client_bot_id=client_bot.id,
            client_id=client_bot.client_id,
            viewer_id=viewer.id,
        )

        await self.session.commit()
        return {
            "ok": True,
            "action": "viewer_start",
            "is_new": is_new,
            "viewer_id": viewer.id,
            "catchup_queued": catchup_queued,
        }

    async def handle_viewer_help(
        self,
        client_bot: ClientBot,
        telegram_user_id: int,
        chat_id: int,
        telegram_client: TelegramClient,
    ) -> Dict[str, Any]:
        """Handles /help command for a normal viewer."""
        viewer = await self.viewer_repo.get_by_bot_and_telegram_user(
            client_bot_id=client_bot.id,
            telegram_user_id=telegram_user_id,
        )
        if viewer:
            viewer.last_seen_at = utc_now()
            await self.session.commit()

        await telegram_client.send_message(
            chat_id=chat_id,
            text=messages.viewer_help_message(bot_username=client_bot.username),
        )
        return {"ok": True, "action": "viewer_help"}

    async def handle_viewer_default_reply(
        self,
        client_bot: ClientBot,
        telegram_user_id: int,
        chat_id: int,
        telegram_client: TelegramClient,
    ) -> Dict[str, Any]:
        """Handles unrecognized message/text for a normal viewer by sending configured fallback."""
        viewer = await self.viewer_repo.get_by_bot_and_telegram_user(
            client_bot_id=client_bot.id,
            telegram_user_id=telegram_user_id,
        )
        if viewer:
            viewer.last_seen_at = utc_now()
            await self.session.commit()

        settings = await self.get_bot_settings(client_bot.id)
        default_reply = settings.default_message if settings and settings.default_message else None

        await telegram_client.send_message(
            chat_id=chat_id,
            text=messages.default_reply_message(custom_default=default_reply),
        )
        return {"ok": True, "action": "viewer_default_reply"}

    async def check_and_enqueue_catchup(
        self,
        client_bot_id: int,
        client_id: int,
        viewer_id: int,
    ) -> bool:
        """Determines if the viewer needs historical video catch-up and initializes/queues catchup state."""
        catchup, job = await self.catchup_service.initialize_or_resume_catchup(
            client_bot_id=client_bot_id,
            viewer_id=viewer_id,
        )
        return job is not None

    async def mark_viewer_blocked(self, client_bot_id: int, telegram_user_id: int) -> Optional[Viewer]:
        """Marks a viewer as blocked when outgoing deliveries encounter Forbidden / Blocked errors."""
        viewer = await self.viewer_repo.mark_blocked(client_bot_id=client_bot_id, telegram_user_id=telegram_user_id)
        await self.session.commit()
        return viewer
