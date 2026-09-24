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

        # Instantiate ViewerService
        from app.services.viewer_service import ViewerService
        from app.db.models.client_bot import ClientBot

        viewer_service = ViewerService(session)
        # Fetch or mock ClientBot model
        bot_model = await session.get(ClientBot, bot_ctx.client_bot_id)
        if not bot_model:
            bot_model = ClientBot(
                id=bot_ctx.client_bot_id,
                client_id=bot_ctx.client_id,
                telegram_bot_id=bot_ctx.telegram_bot_id,
                username=bot_ctx.bot_username,
                display_name=bot_ctx.display_name,
                status=bot_ctx.status,
            )

        # 1. Handle Viewer /start
        if cmd == "/start":
            return await viewer_service.handle_viewer_start(
                client_bot=bot_model,
                telegram_user_id=actor.telegram_user_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                username=actor.username,
                first_name=actor.first_name,
                last_name=actor.last_name,
                language_code=actor.language_code,
            )

        # 2. Handle Viewer /help
        if cmd == "/help":
            return await viewer_service.handle_viewer_help(
                client_bot=bot_model,
                telegram_user_id=actor.telegram_user_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
            )

        # 3. Any unrecognized message / text -> Send custom default_message
        return await viewer_service.handle_viewer_default_reply(
            client_bot=bot_model,
            telegram_user_id=actor.telegram_user_id,
            chat_id=actor.chat_id,
            telegram_client=self.telegram_client,
        )

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
