"""Control Hub Update & Command Router with role guards and navigation."""

from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.enums import ControlHubRole
from app.logging_config import get_logger
from app.services.control_hub_service import ControlHubService
from app.telegram.client import TelegramClient
from app.telegram.control_hub import guards, keyboards, messages

logger = get_logger(__name__)


class ControlHubRouter:
    """Dispatches incoming Telegram updates for the Control Hub Bot."""

    def __init__(self, telegram_client: Optional[TelegramClient] = None):
        self.telegram_client = telegram_client or TelegramClient(
            token=get_settings().CONTROL_HUB_BOT_TOKEN or ""
        )

    async def process_update(
        self,
        update: Dict[str, Any],
        session: AsyncSession,
    ) -> Dict[str, Any]:
        """Main entry point for processing a raw Telegram webhook update."""
        service = ControlHubService(session)

        # 1. Handle Message Updates
        if "message" in update:
            return await self._handle_message(update["message"], service)

        # 2. Handle Callback Query Updates
        if "callback_query" in update:
            return await self._handle_callback_query(update["callback_query"], service)

        logger.debug(f"Unhandled update type: {list(update.keys())}")
        return {"ok": True, "action": "ignored"}

    async def _handle_message(
        self,
        msg: Dict[str, Any],
        service: ControlHubService,
    ) -> Dict[str, Any]:
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        from_user = msg.get("from", {})
        user_id = from_user.get("id")
        text = (msg.get("text") or "").strip()

        if not chat_id or not user_id:
            return {"ok": False, "error": "missing_chat_or_user"}

        # Guard: Check private chat requirement
        if not guards.is_private_chat(chat_type):
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.private_chat_only_message(),
            )
            return {"ok": True, "action": "rejected_non_private"}

        # Resolve User Role
        role = await service.resolve_role(user_id)
        is_owner = role == ControlHubRole.PLATFORM_OWNER

        # Command Dispatcher
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            command = parts[0].lower().split("@")[0]  # strip @botusername if present
            args = parts[1] if len(parts) > 1 else None
            return await self._dispatch_command(command, args, chat_id, user_id, from_user, is_owner, service)

        # Non-command Text Handling
        text_reply = messages.normal_text_reply_message(is_owner=is_owner)
        markup = keyboards.owner_home_keyboard() if is_owner else keyboards.client_home_keyboard()
        await self.telegram_client.send_message(
            chat_id=chat_id,
            text=text_reply,
            reply_markup=markup,
        )
        return {"ok": True, "action": "text_reply"}

    async def _dispatch_command(
        self,
        command: str,
        args: Optional[str],
        chat_id: int,
        user_id: int,
        from_user: Dict[str, Any],
        is_owner: bool,
        service: ControlHubService,
    ) -> Dict[str, Any]:
        """Routes command strings to appropriate handlers based on authorization."""
        username = from_user.get("username")
        first_name = from_user.get("first_name")
        last_name = from_user.get("last_name")

        # --- /start Command ---
        if command == "/start":
            if is_owner:
                await self.telegram_client.send_message(
                    chat_id=chat_id,
                    text=messages.owner_home_message(),
                    reply_markup=keyboards.owner_home_keyboard(),
                )
                return {"ok": True, "action": "owner_home"}

            # Client or New Client
            client, is_new = await service.get_or_create_client(
                telegram_user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            bots = await service.list_client_bots(client.id)

            if is_new or len(bots) == 0:
                await self.telegram_client.send_message(
                    chat_id=chat_id,
                    text=messages.new_client_welcome_message(),
                    reply_markup=keyboards.new_client_keyboard(),
                )
                return {"ok": True, "action": "new_client_welcome"}

            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.client_home_message(username=client.username, bot_count=len(bots)),
                reply_markup=keyboards.client_home_keyboard(),
            )
            return {"ok": True, "action": "client_home"}

        # --- Platform Owner Only Commands ---
        owner_commands = {
            "/clients",
            "/bots",
            "/jobs",
            "/queue",
            "/broadcasts",
            "/systemstats",
        }
        if command in owner_commands:
            if not is_owner:
                await self.telegram_client.send_message(
                    chat_id=chat_id,
                    text=messages.unauthorized_message(),
                )
                return {"ok": True, "action": "unauthorized"}

            return await self._handle_owner_command(command, chat_id, service)

        # --- Client Commands ---
        if command == "/connectbot":
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.client_connectbot_entry_message(),
                reply_markup=keyboards.connectbot_entry_keyboard(),
            )
            return {"ok": True, "action": "client_connectbot"}

        if command == "/mybots":
            client = await service.get_client_by_telegram_id(user_id)
            bots = await service.list_client_bots(client.id) if client else []
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.client_mybots_message(bots),
                reply_markup=keyboards.mybots_keyboard(),
            )
            return {"ok": True, "action": "client_mybots"}

        if command == "/account":
            client = await service.get_client_by_telegram_id(user_id)
            if not client:
                client, _ = await service.get_or_create_client(user_id, username, first_name, last_name)
            summary = await service.get_client_account_summary(client.id)
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.client_account_message(
                    username=summary.get("username"),
                    bot_count=summary.get("total_bots", 0),
                    status=summary.get("status", "ACTIVE"),
                ),
                reply_markup=keyboards.back_to_client_home_keyboard(),
            )
            return {"ok": True, "action": "client_account"}

        if command in ("/botstatus", "/disconnectbot"):
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text="🤖 Use /mybots to select a bot and manage its status or disconnection.",
                reply_markup=keyboards.mybots_keyboard(),
            )
            return {"ok": True, "action": "client_bot_management_info"}

        if command == "/help":
            help_text = messages.owner_help_message() if is_owner else messages.client_help_message()
            markup = (
                keyboards.back_to_owner_home_keyboard()
                if is_owner
                else keyboards.back_to_client_home_keyboard()
            )
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=help_text,
                reply_markup=markup,
            )
            return {"ok": True, "action": "help"}

        # --- Unknown Command ---
        await self.telegram_client.send_message(
            chat_id=chat_id,
            text=messages.unknown_command_message(is_owner=is_owner),
        )
        return {"ok": True, "action": "unknown_command"}

    async def _handle_owner_command(
        self,
        command: str,
        chat_id: int,
        service: ControlHubService,
    ) -> Dict[str, Any]:
        """Executes owner-only commands."""
        stats = await service.get_owner_system_stats()

        if command == "/clients":
            text = messages.owner_clients_message(
                total=stats["total_clients"],
                active=stats["total_clients"],
            )
        elif command == "/bots":
            text = messages.owner_bots_message(
                total=stats["total_bots"],
                active=stats["active_bots"],
                paused=stats["paused_bots"],
                disconnected=stats["disconnected_bots"],
            )
        elif command == "/jobs":
            text = messages.owner_jobs_message(
                running=stats["processing_jobs"],
                failed=stats["failed_items"],
            )
        elif command == "/queue":
            text = messages.owner_queue_message()
        elif command == "/broadcasts":
            text = messages.owner_broadcasts_message(
                running=stats["running_broadcasts"],
            )
        elif command == "/systemstats":
            text = messages.owner_systemstats_message(stats)
        else:
            text = messages.owner_home_message()

        await self.telegram_client.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboards.back_to_owner_home_keyboard(),
        )
        return {"ok": True, "action": f"owner_{command[1:]}"}

    async def _handle_callback_query(
        self,
        cq: Dict[str, Any],
        service: ControlHubService,
    ) -> Dict[str, Any]:
        """Handles inline keyboard button callbacks."""
        cq_id = cq.get("id")
        from_user = cq.get("from", {})
        user_id = from_user.get("id")
        msg = cq.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        message_id = msg.get("message_id")
        data = cq.get("data", "")

        if cq_id:
            try:
                await self.telegram_client.answer_callback_query(cq_id)
            except Exception as exc:
                logger.warning(f"Could not answer callback query: {exc}")

        if not chat_id or not user_id or not message_id:
            return {"ok": False, "error": "missing_callback_context"}

        role = await service.resolve_role(user_id)
        is_owner = role == ControlHubRole.PLATFORM_OWNER

        # --- Owner Callbacks ---
        if data.startswith("owner:"):
            if not is_owner:
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.unauthorized_message(),
                )
                return {"ok": True, "action": "unauthorized_callback"}

            action = data.split(":", 1)[1]
            return await self._handle_owner_command(f"/{action}", chat_id, service)

        # --- Client Callbacks ---
        if data == "client:mybots":
            client = await service.get_client_by_telegram_id(user_id)
            bots = await service.list_client_bots(client.id) if client else []
            await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=messages.client_mybots_message(bots),
                reply_markup=keyboards.mybots_keyboard(),
            )
            return {"ok": True, "action": "cb_client_mybots"}

        if data in ("client:connectbot", "client:connectbot_start"):
            await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=messages.client_connectbot_entry_message(),
                reply_markup=keyboards.connectbot_entry_keyboard(),
            )
            return {"ok": True, "action": "cb_client_connectbot"}

        if data == "client:account":
            client = await service.get_client_by_telegram_id(user_id)
            if not client:
                client, _ = await service.get_or_create_client(
                    user_id, from_user.get("username"), from_user.get("first_name"), from_user.get("last_name")
                )
            summary = await service.get_client_account_summary(client.id)
            await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=messages.client_account_message(
                    username=summary.get("username"),
                    bot_count=summary.get("total_bots", 0),
                    status=summary.get("status", "ACTIVE"),
                ),
                reply_markup=keyboards.back_to_client_home_keyboard(),
            )
            return {"ok": True, "action": "cb_client_account"}

        if data == "client:help":
            await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=messages.client_help_message(),
                reply_markup=keyboards.back_to_client_home_keyboard(),
            )
            return {"ok": True, "action": "cb_client_help"}

        # --- Navigation Callbacks ---
        if data == "nav:owner_home":
            if is_owner:
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_home_message(),
                    reply_markup=keyboards.owner_home_keyboard(),
                )
            return {"ok": True, "action": "cb_nav_owner_home"}

        if data == "nav:client_home":
            client = await service.get_client_by_telegram_id(user_id)
            bot_count = len(await service.list_client_bots(client.id)) if client else 0
            await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=messages.client_home_message(
                    username=from_user.get("username"), bot_count=bot_count
                ),
                reply_markup=keyboards.client_home_keyboard(),
            )
            return {"ok": True, "action": "cb_nav_client_home"}

        return {"ok": True, "action": "unhandled_callback"}
