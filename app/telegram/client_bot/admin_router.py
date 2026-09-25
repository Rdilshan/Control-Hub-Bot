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

        from app.services.video_creation_service import VideoCreationService
        from app.db.models.client_bot import ClientBot

        video_service = VideoCreationService(session)
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

        # 1. Check if Admin is in video intake, sponsor configuration, or custom messages state
        from app.telegram.client_bot.admin.custom_messages import (
            WAITING_FOR_DEFAULT_MESSAGE,
            WAITING_FOR_START_MESSAGE,
            clear_messages_state,
            get_messages_state,
            handle_defaultmessage_command,
            handle_startmessage_command,
        )
        from app.telegram.client_bot.admin.sponsor import (
            WAITING_FOR_SPONSOR_URL,
            apply_sponsor_url,
            clear_sponsor_state,
            get_sponsor_state,
            handle_sponsor_command,
        )

        messages_state = await get_messages_state(
            client_bot_id=bot_ctx.client_bot_id,
            telegram_user_id=actor.telegram_user_id,
        )
        if messages_state == WAITING_FOR_START_MESSAGE:
            if cmd in ("/cancel", "cancel"):
                await clear_messages_state(bot_ctx.client_bot_id, actor.telegram_user_id)
                await self.telegram_client.send_message(
                    chat_id=actor.chat_id,
                    text="❌ Custom start message setup cancelled.",
                )
                return {"ok": True, "action": "admin_startmessage_cancel"}
            if not cmd.startswith("/"):
                return await handle_startmessage_command(
                    client_bot_id=bot_ctx.client_bot_id,
                    telegram_user_id=actor.telegram_user_id,
                    chat_id=actor.chat_id,
                    text=f"/startmessage {text}",
                    telegram_client=self.telegram_client,
                    session=session,
                )

        if messages_state == WAITING_FOR_DEFAULT_MESSAGE:
            if cmd in ("/cancel", "cancel"):
                await clear_messages_state(bot_ctx.client_bot_id, actor.telegram_user_id)
                await self.telegram_client.send_message(
                    chat_id=actor.chat_id,
                    text="❌ Custom default message setup cancelled.",
                )
                return {"ok": True, "action": "admin_defaultmessage_cancel"}
            if not cmd.startswith("/"):
                return await handle_defaultmessage_command(
                    client_bot_id=bot_ctx.client_bot_id,
                    telegram_user_id=actor.telegram_user_id,
                    chat_id=actor.chat_id,
                    text=f"/defaultmessage {text}",
                    telegram_client=self.telegram_client,
                    session=session,
                )

        sponsor_state = await get_sponsor_state(
            client_bot_id=bot_ctx.client_bot_id,
            telegram_user_id=actor.telegram_user_id,
        )
        if sponsor_state == WAITING_FOR_SPONSOR_URL:
            if cmd in ("/cancel", "cancel"):
                await clear_sponsor_state(bot_ctx.client_bot_id, actor.telegram_user_id)
                await self.telegram_client.send_message(
                    chat_id=actor.chat_id,
                    text="❌ Sponsor setup cancelled.",
                )
                return {"ok": True, "action": "admin_sponsor_cancel"}
            if not cmd.startswith("/"):
                return await apply_sponsor_url(
                    client_bot_id=bot_ctx.client_bot_id,
                    telegram_user_id=actor.telegram_user_id,
                    chat_id=actor.chat_id,
                    url=text.strip(),
                    telegram_client=self.telegram_client,
                    session=session,
                )

        creation_state = await video_service.get_creation_state(
            client_bot_id=bot_ctx.client_bot_id,
            telegram_user_id=actor.telegram_user_id,
        )

        if creation_state in ("WAITING_FOR_VIDEO", "ACCEPTING_VIDEO"):
            if cmd in ("/cancel", "cancel"):
                from app.telegram.client_bot.admin.createvideo import handle_cancel_command
                return await handle_cancel_command(
                    client_bot_id=bot_ctx.client_bot_id,
                    telegram_user_id=actor.telegram_user_id,
                    chat_id=actor.chat_id,
                    telegram_client=self.telegram_client,
                    session=session,
                )
            # If not a navigation command like /start, process the video intake
            if not cmd.startswith("/start"):
                from app.telegram.client_bot.admin.video_input import handle_video_input
                return await handle_video_input(
                    client_bot=bot_model,
                    telegram_user_id=actor.telegram_user_id,
                    chat_id=actor.chat_id,
                    admin_id=actor.admin_record_id,
                    actor_data=actor_data,
                    telegram_client=self.telegram_client,
                    session=session,
                )

        # 2. Check /createvideo command
        if cmd == "/createvideo":
            from app.telegram.client_bot.admin.createvideo import handle_createvideo_command
            return await handle_createvideo_command(
                client_bot=bot_model,
                telegram_user_id=actor.telegram_user_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
            )

        # 3. Check /sponsor command
        if cmd == "/sponsor" or cmd.startswith("/sponsor"):
            return await handle_sponsor_command(
                client_bot_id=bot_ctx.client_bot_id,
                telegram_user_id=actor.telegram_user_id,
                chat_id=actor.chat_id,
                text=text,
                telegram_client=self.telegram_client,
                session=session,
            )

        # 4. Check /videos command
        if cmd == "/videos":
            from app.telegram.client_bot.admin.videos import handle_videos_command
            return await handle_videos_command(
                client_bot_id=bot_ctx.client_bot_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
            )

        # 5. Check /processing command
        if cmd == "/processing":
            from app.telegram.client_bot.admin.processing import handle_processing_command
            return await handle_processing_command(
                client_bot_id=bot_ctx.client_bot_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
            )

        # 6. Check /stats command
        if cmd == "/stats":
            from app.telegram.client_bot.admin.stats import handle_stats_command
            return await handle_stats_command(
                client_bot_id=bot_ctx.client_bot_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
            )

        # 7. Check /users command
        if cmd == "/users":
            from app.telegram.client_bot.admin.users import handle_users_command
            return await handle_users_command(
                client_bot_id=bot_ctx.client_bot_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
            )

        # 8. Check /broadcasts command
        if cmd == "/broadcasts":
            from app.telegram.client_bot.admin.broadcasts import handle_broadcasts_command
            return await handle_broadcasts_command(
                client_bot_id=bot_ctx.client_bot_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
            )

        # 9. Check /startmessage command
        if cmd == "/startmessage" or cmd.startswith("/startmessage"):
            from app.telegram.client_bot.admin.custom_messages import handle_startmessage_command
            return await handle_startmessage_command(
                client_bot_id=bot_ctx.client_bot_id,
                telegram_user_id=actor.telegram_user_id,
                chat_id=actor.chat_id,
                text=text,
                telegram_client=self.telegram_client,
                session=session,
            )

        # 10. Check /defaultmessage command
        if cmd == "/defaultmessage" or cmd.startswith("/defaultmessage"):
            from app.telegram.client_bot.admin.custom_messages import handle_defaultmessage_command
            return await handle_defaultmessage_command(
                client_bot_id=bot_ctx.client_bot_id,
                telegram_user_id=actor.telegram_user_id,
                chat_id=actor.chat_id,
                text=text,
                telegram_client=self.telegram_client,
                session=session,
            )

        # 11. Check /cancel outside session
        if cmd in ("/cancel", "cancel"):
            await clear_messages_state(bot_ctx.client_bot_id, actor.telegram_user_id)
            await clear_sponsor_state(bot_ctx.client_bot_id, actor.telegram_user_id)
            await video_service.clear_creation_state(bot_ctx.client_bot_id, actor.telegram_user_id)
            await self.telegram_client.send_message(
                chat_id=actor.chat_id,
                text="❌ No active operation to cancel.",
            )
            return {"ok": True, "action": "admin_cancel_noop"}

        if cmd in ("/start", "/help"):
            parts = text.split(maxsplit=1)
            start_param = parts[1].strip() if len(parts) > 1 else None

            if cmd == "/start" and start_param and start_param.startswith("unlock_"):
                from app.telegram.client_bot.viewer.unlock import handle_viewer_unlock_command
                return await handle_viewer_unlock_command(
                    client_bot=bot_model,
                    telegram_user_id=actor.telegram_user_id,
                    chat_id=actor.chat_id,
                    payload=start_param,
                    actor_data=actor_data,
                    telegram_client=self.telegram_client,
                    session=session,
                )

            await clear_messages_state(bot_ctx.client_bot_id, actor.telegram_user_id)
            await clear_sponsor_state(bot_ctx.client_bot_id, actor.telegram_user_id)
            await video_service.clear_creation_state(bot_ctx.client_bot_id, actor.telegram_user_id)
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
        msg_id = actor_data.get("message_id") or actor_data.get("message", {}).get("message_id")

        if cb_id:
            await self.telegram_client.answer_callback_query(callback_query_id=cb_id)

        from app.db.models.client_bot import ClientBot

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

        if cb_data == "admin:createvideo":
            from app.telegram.client_bot.admin.createvideo import handle_createvideo_command
            return await handle_createvideo_command(
                client_bot=bot_model,
                telegram_user_id=actor.telegram_user_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
            )

        if cb_data == "admin:videos":
            from app.telegram.client_bot.admin.videos import handle_videos_command
            return await handle_videos_command(
                client_bot_id=bot_ctx.client_bot_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
            )

        if cb_data in ("admin:processing", "admin:processing:refresh"):
            from app.telegram.client_bot.admin.processing import handle_processing_command
            return await handle_processing_command(
                client_bot_id=bot_ctx.client_bot_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
                bypass_cache=cb_data.endswith(":refresh"),
                message_id=msg_id if cb_data.endswith(":refresh") else None,
            )

        if cb_data in ("admin:stats", "admin:stats:refresh"):
            from app.telegram.client_bot.admin.stats import handle_stats_command
            return await handle_stats_command(
                client_bot_id=bot_ctx.client_bot_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
                bypass_cache=cb_data.endswith(":refresh"),
                message_id=msg_id if cb_data.endswith(":refresh") else None,
            )

        if cb_data in ("admin:users", "admin:users:refresh"):
            from app.telegram.client_bot.admin.users import handle_users_command
            return await handle_users_command(
                client_bot_id=bot_ctx.client_bot_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
                bypass_cache=cb_data.endswith(":refresh"),
                message_id=msg_id if cb_data.endswith(":refresh") else None,
            )

        if cb_data in ("admin:broadcasts", "admin:broadcasts:refresh"):
            from app.telegram.client_bot.admin.broadcasts import handle_broadcasts_command
            return await handle_broadcasts_command(
                client_bot_id=bot_ctx.client_bot_id,
                chat_id=actor.chat_id,
                telegram_client=self.telegram_client,
                session=session,
                bypass_cache=cb_data.endswith(":refresh"),
                message_id=msg_id if cb_data.endswith(":refresh") else None,
            )

        if cb_data == "admin:dashboard":
            await self.telegram_client.send_message(
                chat_id=actor.chat_id,
                text=messages.admin_welcome_message(
                    bot_username=bot_ctx.bot_username,
                    display_name=bot_ctx.display_name,
                    client_first_name=actor.first_name,
                ),
                reply_markup=keyboards.admin_dashboard_keyboard(),
            )
            return {"ok": True, "action": "admin_dashboard"}

        if cb_data.startswith("admin:sponsor"):
            from app.telegram.client_bot.admin.sponsor import handle_sponsor_callback
            return await handle_sponsor_callback(
                client_bot_id=bot_ctx.client_bot_id,
                telegram_user_id=actor.telegram_user_id,
                chat_id=actor.chat_id,
                callback_data=cb_data,
                telegram_client=self.telegram_client,
                session=session,
            )

        if cb_data.startswith("admin:messages") or cb_data.startswith("admin:startmessage") or cb_data.startswith("admin:defaultmessage"):
            from app.telegram.client_bot.admin.custom_messages import handle_custom_messages_callback
            return await handle_custom_messages_callback(
                client_bot_id=bot_ctx.client_bot_id,
                telegram_user_id=actor.telegram_user_id,
                chat_id=actor.chat_id,
                callback_data=cb_data,
                telegram_client=self.telegram_client,
                session=session,
            )

        resp_text = "👑 Admin action received."
        await self.telegram_client.send_message(chat_id=actor.chat_id, text=resp_text)
        return {"ok": True, "action": f"admin_callback_{cb_data}"}
