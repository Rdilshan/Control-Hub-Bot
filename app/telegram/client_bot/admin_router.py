"""Client Admin Router handling verified administrator interactions."""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.logging_config import get_logger
from app.telegram.client import TelegramClient
from app.telegram.client_bot import keyboards, messages
from app.telegram.client_bot.context import ClientBotActorContext, ClientBotContext

logger = get_logger(__name__)


class ClientAdminRouter:
    """Routes updates from verified Client Bot administrators."""

    def __init__(self, telegram_client: TelegramClient):
        self.telegram_client = telegram_client

    async def handle(
        self,
        bot_ctx: ClientBotContext,
        actor: ClientBotActorContext,
        actor_data: Dict[str, Any],
        session: AsyncSession,
    ) -> Dict[str, Any]:
        """Main dispatcher for admin updates."""
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

        if cmd in ("/start", "/help"):
            await self.telegram_client.send_message(
                chat_id=actor.chat_id,
                text=messages.admin_welcome_message(
                    bot_username=bot_ctx.bot_username,
                    display_name=bot_ctx.display_name,
                    client_first_name=actor.first_name,
                ),
                reply_markup=keyboards.admin_dashboard_keyboard(),
            )
            return {"ok": True, "action": "admin_start"}

        # Built-in Admin Commands (Full workflows implemented in Stage 08+)
        admin_commands = {
            "/createvideo": "🎬 <b>Create Video</b>\n\nVideo uploading & publishing engine will activate here. (Stage 10)",
            "/stats": "📊 <b>Bot Analytics</b>\n\nViewer counts, video views, and unlock statistics will display here. (Stage 17)",
            "/videos": "📁 <b>Video Library</b>\n\nYour published video collection and management will appear here.",
            "/processing": "⏳ <b>Processing Queue</b>\n\nCurrently active video background jobs will show here.",
            "/users": "👥 <b>Viewer Audience</b>\n\nSubscriber metrics and viewer management will appear here.",
            "/broadcasts": "📢 <b>Broadcast Campaigns</b>\n\nCompose and schedule audience broadcasts here.",
            "/sponsor": "🔓 <b>Sponsor Configuration</b>\n\nConfigure your Unlockify API keys and monetization links here. (Stage 12)",
            "/startmessage": "💬 <b>Custom Start Message</b>\n\nCustomize the welcome message shown to new viewers.",
            "/defaultmessage": "🔁 <b>Default Reply Message</b>\n\nCustomize the fallback response for unrecognized viewer messages.",
        }

        if cmd in admin_commands:
            await self.telegram_client.send_message(
                chat_id=actor.chat_id,
                text=admin_commands[cmd],
            )
            return {"ok": True, "action": f"admin_cmd_{cmd.lstrip('/')}"}

        # Any other message sent by admin
        await self.telegram_client.send_message(
            chat_id=actor.chat_id,
            text=messages.admin_welcome_message(
                bot_username=bot_ctx.bot_username,
                display_name=bot_ctx.display_name,
                client_first_name=actor.first_name,
            ),
            reply_markup=keyboards.admin_dashboard_keyboard(),
        )
        return {"ok": True, "action": "admin_default"}

    async def _handle_callback_query(
        self,
        bot_ctx: ClientBotContext,
        actor: ClientBotActorContext,
        actor_data: Dict[str, Any],
        session: AsyncSession,
    ) -> Dict[str, Any]:
        cb_id = actor_data.get("callback_query_id")
        cb_data = actor_data.get("callback_data") or ""

        if cb_id:
            await self.telegram_client.answer_callback_query(callback_query_id=cb_id)

        responses = {
            "admin:createvideo": "🎬 Send /createvideo to start a new video publishing session.",
            "admin:stats": "📊 Send /stats to view full performance analytics.",
            "admin:videos": "📁 Send /videos to inspect published content.",
            "admin:processing": "⏳ Send /processing to inspect active conversion queue.",
            "admin:users": "👥 Send /users to view audience growth.",
            "admin:broadcasts": "📢 Send /broadcasts to create and launch broadcasts.",
            "admin:sponsor": "🔓 Send /sponsor to manage Unlockify monetization settings.",
            "admin:messages": "💬 Send /startmessage or /defaultmessage to customize greetings.",
        }

        resp_text = responses.get(cb_data, "👑 Admin action received.")
        await self.telegram_client.send_message(chat_id=actor.chat_id, text=resp_text)
        return {"ok": True, "action": f"admin_callback_{cb_data}"}
