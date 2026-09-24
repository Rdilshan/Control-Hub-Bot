"""Viewer Router handling normal viewers and subscribers."""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.client_bot_settings import ClientBotSettings
from app.logging_config import get_logger
from app.repositories.viewer import ViewerRepository
from app.telegram.client import TelegramClient
from app.telegram.client_bot import messages
from app.telegram.client_bot.context import ClientBotActorContext, ClientBotContext

logger = get_logger(__name__)


class ClientViewerRouter:
    """Routes updates from normal viewers."""

    def __init__(self, telegram_client: TelegramClient):
        self.telegram_client = telegram_client

    async def handle(
        self,
        bot_ctx: ClientBotContext,
        actor: ClientBotActorContext,
        actor_data: Dict[str, Any],
        session: AsyncSession,
    ) -> Dict[str, Any]:
        """Main dispatcher for normal viewer updates."""
        update_type = actor_data.get("update_type")
        if update_type == "callback_query":
            return await self._handle_callback_query(bot_ctx, actor, actor_data, session)
        return await self._handle_message(bot_ctx, actor, actor_data, session)

    async def _handle_message(
        self,
        bot_ctx: ClientBotContext,
        actor: ClientBotActorContext,
        actor_data: Dict[str, Any],
        session: AsyncSession,
    ) -> Dict[str, Any]:
        text = actor_data.get("text") or ""
        cmd = text.lower().split()[0] if text.startswith("/") else ""

        # Fetch custom bot settings if available
        settings_stmt = select(ClientBotSettings).where(ClientBotSettings.client_bot_id == bot_ctx.client_bot_id)
        settings_res = await session.execute(settings_stmt)
        bot_settings = settings_res.scalar_one_or_none()

        # 1. Handle Viewer /start
        if cmd == "/start":
            viewer_repo = ViewerRepository(session)
            await viewer_repo.get_or_create_viewer(
                client_bot_id=bot_ctx.client_bot_id,
                telegram_user_id=actor.telegram_user_id,
                username=actor.username,
                first_name=actor.first_name,
                last_name=actor.last_name,
                language_code=actor.language_code,
            )
            await session.commit()

            start_text = bot_settings.start_message if bot_settings and bot_settings.start_message else None
            await self.telegram_client.send_message(
                chat_id=actor.chat_id,
                text=messages.viewer_welcome_message(
                    custom_start_message=start_text,
                    bot_username=bot_ctx.bot_username,
                ),
            )
            return {"ok": True, "action": "viewer_start"}

        # 2. Handle Viewer /help
        if cmd == "/help":
            await self.telegram_client.send_message(
                chat_id=actor.chat_id,
                text=messages.viewer_help_message(bot_username=bot_ctx.bot_username),
            )
            return {"ok": True, "action": "viewer_help"}

        # 3. Any unrecognized message / text -> Send custom default_message
        default_reply = bot_settings.default_message if bot_settings and bot_settings.default_message else None
        await self.telegram_client.send_message(
            chat_id=actor.chat_id,
            text=messages.default_reply_message(custom_default=default_reply),
        )
        return {"ok": True, "action": "viewer_default_reply"}

    async def _handle_callback_query(
        self,
        bot_ctx: ClientBotContext,
        actor: ClientBotActorContext,
        actor_data: Dict[str, Any],
        session: AsyncSession,
    ) -> Dict[str, Any]:
        cb_id = actor_data.get("callback_query_id")
        if cb_id:
            await self.telegram_client.answer_callback_query(callback_query_id=cb_id)
        return {"ok": True, "action": "viewer_callback_handled"}
