"""Control Hub Update & Command Router with role guards, full Owner management, and navigation."""

from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.enums import (
    BroadcastStatus,
    ClientStatus,
    ControlHubRole,
    JobStatus,
)
from app.logging_config import get_logger
from app.redis.client import get_redis
from app.services.control_hub_service import ControlHubService
from app.services.platform_owner_service import PlatformOwnerService
from app.telegram.client import TelegramClient
from app.telegram.control_hub import guards, keyboards, messages

logger = get_logger(__name__)

SEARCH_STATE_PREFIX = "controlhub:owner:search_state:"
SEARCH_STATE_TTL = 600  # 10 minutes


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
        owner_service = PlatformOwnerService(session)

        # 1. Handle Message Updates
        if "message" in update:
            return await self._handle_message(update["message"], service, owner_service)

        # 2. Handle Callback Query Updates
        if "callback_query" in update:
            return await self._handle_callback_query(update["callback_query"], service, owner_service)

        logger.debug(f"Unhandled update type: {list(update.keys())}")
        return {"ok": True, "action": "ignored"}

    async def _handle_message(
        self,
        msg: Dict[str, Any],
        service: ControlHubService,
        owner_service: PlatformOwnerService,
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

        # Check for /cancel command
        if text.lower() in ("/cancel", "cancel"):
            try:
                redis = get_redis()
                await redis.delete(f"{SEARCH_STATE_PREFIX}{user_id}")
            except Exception:
                pass
            if is_owner:
                await self.telegram_client.send_message(
                    chat_id=chat_id,
                    text="❌ Search cancelled.",
                    reply_markup=keyboards.back_to_owner_home_keyboard(),
                )
            else:
                await self.telegram_client.send_message(
                    chat_id=chat_id,
                    text="❌ Action cancelled.",
                    reply_markup=keyboards.back_to_client_home_keyboard(),
                )
            return {"ok": True, "action": "cancelled"}

        # Check Owner Pending Search State in Redis
        if is_owner and not text.startswith("/"):
            try:
                redis = get_redis()
                state = await redis.get(f"{SEARCH_STATE_PREFIX}{user_id}")
                if state:
                    await redis.delete(f"{SEARCH_STATE_PREFIX}{user_id}")
                    if state == "WAITING_FOR_CLIENT_SEARCH":
                        return await self._handle_client_search_query(text, chat_id, owner_service)
                    elif state == "WAITING_FOR_BOT_SEARCH":
                        return await self._handle_bot_search_query(text, chat_id, owner_service)
            except Exception as exc:
                logger.warning(f"Redis search state check error: {exc}")

        # Command Dispatcher
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            command = parts[0].lower().split("@")[0]
            args = parts[1] if len(parts) > 1 else None
            return await self._dispatch_command(
                command, args, chat_id, user_id, from_user, is_owner, service, owner_service
            )

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
        owner_service: PlatformOwnerService,
    ) -> Dict[str, Any]:
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

            # Suspended Client Guard
            if client.status == ClientStatus.SUSPENDED:
                await self.telegram_client.send_message(
                    chat_id=chat_id,
                    text=messages.client_suspended_message(),
                )
                return {"ok": True, "action": "client_suspended"}

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

            return await self._handle_owner_command_view(command, chat_id, owner_service)

        # --- Client Commands ---
        client = await service.get_client_by_telegram_id(user_id)
        if client and client.status == ClientStatus.SUSPENDED:
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.client_suspended_message(),
            )
            return {"ok": True, "action": "client_suspended"}

        if command == "/connectbot":
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.client_connectbot_entry_message(),
                reply_markup=keyboards.connectbot_entry_keyboard(),
            )
            return {"ok": True, "action": "client_connectbot"}

        if command == "/mybots":
            bots = await service.list_client_bots(client.id) if client else []
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.client_mybots_message(bots),
                reply_markup=keyboards.mybots_keyboard(),
            )
            return {"ok": True, "action": "client_mybots"}

        if command == "/account":
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

    # ==========================================================================
    # 👑 Platform Owner Views & Callbacks
    # ==========================================================================

    async def _handle_owner_command_view(
        self,
        command: str,
        chat_id: int,
        owner_service: PlatformOwnerService,
    ) -> Dict[str, Any]:
        if command == "/clients":
            stats = await owner_service.get_client_summary()
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.owner_clients_summary_message(stats),
                reply_markup=keyboards.owner_clients_summary_keyboard(),
            )
            return {"ok": True, "action": "owner_clients"}

        elif command == "/bots":
            stats = await owner_service.get_bot_summary()
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.owner_bots_summary_message(stats),
                reply_markup=keyboards.owner_bots_summary_keyboard(),
            )
            return {"ok": True, "action": "owner_bots"}

        elif command == "/jobs":
            stats = await owner_service.get_job_summary()
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.owner_jobs_summary_message(stats),
                reply_markup=keyboards.owner_jobs_summary_keyboard(),
            )
            return {"ok": True, "action": "owner_jobs"}

        elif command == "/queue":
            stats = await owner_service.get_queue_summary()
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.owner_queue_message(stats),
                reply_markup=keyboards.owner_queue_keyboard(),
            )
            return {"ok": True, "action": "owner_queue"}

        elif command == "/broadcasts":
            stats = await owner_service.get_broadcast_summary()
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.owner_broadcasts_summary_message(stats),
                reply_markup=keyboards.owner_broadcasts_summary_keyboard(),
            )
            return {"ok": True, "action": "owner_broadcasts"}

        elif command == "/systemstats":
            stats = await owner_service.get_system_stats()
            await self.telegram_client.send_message(
                chat_id=chat_id,
                text=messages.owner_systemstats_message(stats),
                reply_markup=keyboards.owner_systemstats_keyboard(),
            )
            return {"ok": True, "action": "owner_systemstats"}

        return {"ok": True, "action": "owner_unknown"}

    async def _handle_client_search_query(
        self, query: str, chat_id: int, owner_service: PlatformOwnerService
    ) -> Dict[str, Any]:
        items = await owner_service.search_clients(query)
        await self.telegram_client.send_message(
            chat_id=chat_id,
            text=messages.owner_client_search_result_message(items, query),
            reply_markup=keyboards.owner_clients_list_keyboard(1, 1, items),
        )
        return {"ok": True, "action": "owner_client_search_results"}

    async def _handle_bot_search_query(
        self, query: str, chat_id: int, owner_service: PlatformOwnerService
    ) -> Dict[str, Any]:
        items = await owner_service.search_bots(query)
        await self.telegram_client.send_message(
            chat_id=chat_id,
            text=messages.owner_bot_search_result_message(items, query),
            reply_markup=keyboards.owner_bots_list_keyboard(1, 1, items),
        )
        return {"ok": True, "action": "owner_bot_search_results"}

    # ==========================================================================
    # 🔘 Callback Query Handling
    # ==========================================================================

    async def _handle_callback_query(
        self,
        cq: Dict[str, Any],
        service: ControlHubService,
        owner_service: PlatformOwnerService,
    ) -> Dict[str, Any]:
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

            return await self._process_owner_callback(data, chat_id, message_id, user_id, owner_service)

        # --- Client Callbacks ---
        client = await service.get_client_by_telegram_id(user_id)
        if client and client.status == ClientStatus.SUSPENDED:
            await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=messages.client_suspended_message(),
            )
            return {"ok": True, "action": "client_suspended"}

        if data == "client:mybots":
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

    async def _process_owner_callback(
        self,
        data: str,
        chat_id: int,
        message_id: int,
        user_id: int,
        owner_service: PlatformOwnerService,
    ) -> Dict[str, Any]:
        parts = data.split(":")
        section = parts[1] if len(parts) > 1 else ""

        # --- 1. Clients Callbacks ---
        if section == "clients":
            if len(parts) == 2:
                stats = await owner_service.get_client_summary()
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_clients_summary_message(stats),
                    reply_markup=keyboards.owner_clients_summary_keyboard(),
                )
                return {"ok": True, "action": "cb_owner_clients_summary"}

            sub = parts[2]
            if sub == "page":
                page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
                items, total, total_pages = await owner_service.list_clients(page=page)
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_clients_list_message(items, page, total_pages),
                    reply_markup=keyboards.owner_clients_list_keyboard(page, total_pages, items),
                )
                return {"ok": True, "action": "cb_owner_clients_list"}

            if sub == "search":
                try:
                    redis = get_redis()
                    await redis.set(f"{SEARCH_STATE_PREFIX}{user_id}", "WAITING_FOR_CLIENT_SEARCH", ex=SEARCH_STATE_TTL)
                except Exception:
                    pass
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_client_search_prompt_message(),
                    reply_markup=keyboards.cancel_search_keyboard(),
                )
                return {"ok": True, "action": "cb_owner_clients_search_prompt"}

        elif section == "client":
            action = parts[2] if len(parts) > 2 else "view"
            client_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

            if action == "view":
                detail = await owner_service.get_client_detail(client_id)
                if not detail:
                    await self.telegram_client.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="⚠️ Client not found or deleted.",
                        reply_markup=keyboards.owner_clients_summary_keyboard(),
                    )
                    return {"ok": True, "action": "client_not_found"}

                is_suspended = detail["client"].status == ClientStatus.SUSPENDED
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_client_detail_message(detail),
                    reply_markup=keyboards.owner_client_detail_keyboard(client_id, is_suspended),
                )
                return {"ok": True, "action": "cb_owner_client_detail"}

            elif action == "suspend":
                detail = await owner_service.get_client_detail(client_id)
                username = detail["client"].username if detail else None
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_client_suspend_confirm_message(username),
                    reply_markup=keyboards.owner_client_suspend_confirm_keyboard(client_id),
                )
                return {"ok": True, "action": "cb_owner_client_suspend_prompt"}

            elif action == "suspend_confirm":
                success, msg, client = await owner_service.suspend_client(client_id, performed_by_owner_id=user_id)
                username = client.username if client else None
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_client_suspended_message(username),
                    reply_markup=keyboards.owner_client_detail_keyboard(client_id, is_suspended=True),
                )
                return {"ok": True, "action": "cb_owner_client_suspended"}

            elif action == "reactivate":
                detail = await owner_service.get_client_detail(client_id)
                username = detail["client"].username if detail else None
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_client_reactivate_confirm_message(username),
                    reply_markup=keyboards.owner_client_reactivate_confirm_keyboard(client_id),
                )
                return {"ok": True, "action": "cb_owner_client_reactivate_prompt"}

            elif action == "reactivate_confirm":
                success, msg, client = await owner_service.reactivate_client(client_id, performed_by_owner_id=user_id)
                username = client.username if client else None
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_client_reactivated_message(username),
                    reply_markup=keyboards.owner_client_detail_keyboard(client_id, is_suspended=False),
                )
                return {"ok": True, "action": "cb_owner_client_reactivated"}

        # --- 2. Bots Callbacks ---
        elif section == "bots":
            if len(parts) == 2:
                stats = await owner_service.get_bot_summary()
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_bots_summary_message(stats),
                    reply_markup=keyboards.owner_bots_summary_keyboard(),
                )
                return {"ok": True, "action": "cb_owner_bots_summary"}

            sub = parts[2]
            if sub == "page":
                page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
                items, total, total_pages = await owner_service.list_bots(page=page)
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_bots_list_message(items, page, total_pages),
                    reply_markup=keyboards.owner_bots_list_keyboard(page, total_pages, items),
                )
                return {"ok": True, "action": "cb_owner_bots_list"}

            if sub == "client":
                client_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
                page = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1
                client_detail = await owner_service.get_client_detail(client_id)
                bots = client_detail["bots"] if client_detail else []
                items = [{"bot": b, "owner": client_detail["client"]} for b in bots] if client_detail else []
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"🤖 <b>Connected Bots for @{client_detail['client'].username if client_detail else client_id}</b>\n\nTotal: {len(bots)}",
                    reply_markup=keyboards.owner_bots_list_keyboard(page, 1, items, client_filter=client_id),
                )
                return {"ok": True, "action": "cb_owner_bots_client"}

            if sub == "search":
                try:
                    redis = get_redis()
                    await redis.set(f"{SEARCH_STATE_PREFIX}{user_id}", "WAITING_FOR_BOT_SEARCH", ex=SEARCH_STATE_TTL)
                except Exception:
                    pass
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_bot_search_prompt_message(),
                    reply_markup=keyboards.cancel_search_keyboard(),
                )
                return {"ok": True, "action": "cb_owner_bots_search_prompt"}

        elif section == "bot":
            action = parts[2] if len(parts) > 2 else "view"
            bot_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

            if action == "view":
                detail = await owner_service.get_bot_detail(bot_id)
                if not detail:
                    await self.telegram_client.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="⚠️ Bot not found.",
                        reply_markup=keyboards.owner_bots_summary_keyboard(),
                    )
                    return {"ok": True, "action": "bot_not_found"}

                client_id = detail["bot"].client_id
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_bot_detail_message(detail),
                    reply_markup=keyboards.owner_bot_detail_keyboard(bot_id, client_id),
                )
                return {"ok": True, "action": "cb_owner_bot_detail"}

        # --- 3. Jobs Callbacks ---
        elif section == "jobs":
            if len(parts) == 2:
                stats = await owner_service.get_job_summary()
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_jobs_summary_message(stats),
                    reply_markup=keyboards.owner_jobs_summary_keyboard(),
                )
                return {"ok": True, "action": "cb_owner_jobs_summary"}

            filter_type = parts[2]
            page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
            status_filter = (
                JobStatus.RUNNING
                if filter_type == "running"
                else JobStatus.FAILED
                if filter_type == "failed"
                else None
            )
            title = "Running Jobs" if filter_type == "running" else "Failed Jobs" if filter_type == "failed" else "All Jobs"
            items, total, total_pages = await owner_service.list_jobs(status=status_filter, page=page)
            await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=messages.owner_jobs_list_message(items, title, page, total_pages),
                reply_markup=keyboards.owner_jobs_list_keyboard(page, total_pages, items, filter_type),
            )
            return {"ok": True, "action": f"cb_owner_jobs_{filter_type}"}

        elif section == "job":
            action = parts[2] if len(parts) > 2 else "view"
            job_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

            if action == "view":
                detail = await owner_service.get_job_detail(job_id)
                if not detail:
                    await self.telegram_client.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="⚠️ Job not found.",
                        reply_markup=keyboards.owner_jobs_summary_keyboard(),
                    )
                    return {"ok": True, "action": "job_not_found"}

                is_retryable = detail["job"].status in (JobStatus.FAILED, JobStatus.RETRYING)
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_job_detail_message(detail),
                    reply_markup=keyboards.owner_job_detail_keyboard(job_id, is_retryable),
                )
                return {"ok": True, "action": "cb_owner_job_detail"}

            elif action == "retry":
                detail = await owner_service.get_job_detail(job_id)
                job_type = detail["job"].job_type.value if detail else "Job"
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_job_retry_confirm_message(job_id, job_type),
                    reply_markup=keyboards.owner_job_retry_confirm_keyboard(job_id),
                )
                return {"ok": True, "action": "cb_owner_job_retry_prompt"}

            elif action == "retry_confirm":
                success, msg, job = await owner_service.retry_job(job_id, performed_by_owner_id=user_id)
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_job_retried_message(success, msg),
                    reply_markup=keyboards.owner_jobs_summary_keyboard(),
                )
                return {"ok": True, "action": "cb_owner_job_retried"}

        # --- 4. Queue Callbacks ---
        elif section == "queue":
            stats = await owner_service.get_queue_summary()
            await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=messages.owner_queue_message(stats),
                reply_markup=keyboards.owner_queue_keyboard(),
            )
            return {"ok": True, "action": "cb_owner_queue"}

        # --- 5. Broadcasts Callbacks ---
        elif section == "broadcasts":
            if len(parts) == 2:
                stats = await owner_service.get_broadcast_summary()
                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_broadcasts_summary_message(stats),
                    reply_markup=keyboards.owner_broadcasts_summary_keyboard(),
                )
                return {"ok": True, "action": "cb_owner_broadcasts_summary"}

            filter_type = parts[2]
            page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
            status_filter = (
                BroadcastStatus.RUNNING
                if filter_type == "running"
                else BroadcastStatus.FAILED
                if filter_type == "failed"
                else None
            )
            title = "Running Broadcasts" if filter_type == "running" else "Failed Broadcasts" if filter_type == "failed" else "All Broadcasts"
            items, total, total_pages = await owner_service.list_broadcasts(status=status_filter, page=page)
            await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=messages.owner_broadcasts_list_message(items, title, page, total_pages),
                reply_markup=keyboards.owner_broadcasts_list_keyboard(page, total_pages, items, filter_type),
            )
            return {"ok": True, "action": f"cb_owner_broadcasts_{filter_type}"}

        elif section == "broadcast":
            action = parts[2] if len(parts) > 2 else "view"
            broadcast_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

            if action == "view":
                detail = await owner_service.get_broadcast_detail(broadcast_id)
                if not detail:
                    await self.telegram_client.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="⚠️ Broadcast not found.",
                        reply_markup=keyboards.owner_broadcasts_summary_keyboard(),
                    )
                    return {"ok": True, "action": "broadcast_not_found"}

                await self.telegram_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=messages.owner_broadcast_detail_message(detail),
                    reply_markup=keyboards.owner_broadcast_detail_keyboard(broadcast_id),
                )
                return {"ok": True, "action": "cb_owner_broadcast_detail"}

        # --- 6. System Stats Callbacks ---
        elif section == "systemstats":
            stats = await owner_service.get_system_stats()
            await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=messages.owner_systemstats_message(stats),
                reply_markup=keyboards.owner_systemstats_keyboard(),
            )
            return {"ok": True, "action": "cb_owner_systemstats"}

        # --- 7. Search Cancel Callback ---
        elif section == "search" and len(parts) > 2 and parts[2] == "cancel":
            try:
                redis = get_redis()
                await redis.delete(f"{SEARCH_STATE_PREFIX}{user_id}")
            except Exception:
                pass
            await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="❌ Search cancelled.",
                reply_markup=keyboards.back_to_owner_home_keyboard(),
            )
            return {"ok": True, "action": "cb_owner_search_cancelled"}

        return {"ok": True, "action": f"owner_unhandled_{section}"}
