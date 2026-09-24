"""Client Bot Dispatcher coordinating bot guards, actor roles, and routing."""

from typing import Any, Dict, Optional, Set
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ClientBotStatus, enum_val
from app.db.models.client_bot import ClientBot
from app.logging_config import get_logger
from app.redis.client import get_redis
from app.repositories.client_bot_admin import ClientBotAdminRepository
from app.telegram.client import TelegramClient
from app.telegram.client_bot import messages
from app.telegram.client_bot.actor import extract_telegram_actor
from app.telegram.client_bot.admin_router import ClientAdminRouter
from app.telegram.client_bot.context import ClientBotActorContext, ClientBotContext
from app.telegram.client_bot.factory import bot_api_factory
from app.telegram.client_bot.viewer_router import ClientViewerRouter

logger = get_logger(__name__)

UPDATE_DEDUP_PREFIX = "controlhub:clientbot:update:"
UPDATE_DEDUP_TTL = 600

# Admin-only commands
ADMIN_COMMANDS: Set[str] = {
    "/createvideo",
    "/stats",
    "/videos",
    "/processing",
    "/users",
    "/broadcasts",
    "/sponsor",
    "/startmessage",
    "/defaultmessage",
}

_in_memory_dedup_store: Set[str] = set()


class ClientBotDispatcher:
    """Dispatches raw Telegram webhook updates for a specific Client Bot."""

    def __init__(self, bot: ClientBot, telegram_client: Optional[TelegramClient] = None):
        self.bot = bot
        self._telegram_client = telegram_client

    def _get_tg_client(self) -> Optional[TelegramClient]:
        if self._telegram_client:
            return self._telegram_client
        if not self.bot.token_encrypted:
            return None
        return bot_api_factory.get_client(self.bot.id, self.bot.token_encrypted)

    async def _is_duplicate_update(self, update_id: int) -> bool:
        """Checks and marks update as processed to prevent retried duplicates."""
        key = f"{UPDATE_DEDUP_PREFIX}{self.bot.id}:{update_id}"
        try:
            redis = get_redis()
            exists = await redis.get(key)
            if exists:
                return True
            await redis.set(key, "1", ex=UPDATE_DEDUP_TTL)
            return False
        except Exception:
            if key in _in_memory_dedup_store:
                return True
            _in_memory_dedup_store.add(key)
            return False

    async def process_update(
        self,
        update: Dict[str, Any],
        session: AsyncSession,
    ) -> Dict[str, Any]:
        """Processes an incoming Telegram webhook update with multi-tenant isolation."""
        update_id = update.get("update_id")
        if update_id and await self._is_duplicate_update(update_id):
            logger.info(f"Skipping duplicate update #{update_id} for bot #{self.bot.id}")
            return {"ok": True, "action": "duplicate_skipped"}

        actor_data = extract_telegram_actor(update)
        if not actor_data:
            return {"ok": True, "action": "unsupported_update_ignored"}

        tg_client = self._get_tg_client()
        if not tg_client:
            logger.error(f"Cannot dispatch update: No TelegramClient for bot #{self.bot.id}")
            return {"ok": False, "error": "bot_client_unavailable"}

        user_id = actor_data["telegram_user_id"]
        chat_id = actor_data["chat_id"]
        chat_type = actor_data["chat_type"]
        text = actor_data.get("text") or ""
        raw_status = enum_val(self.bot.status)

        # 1. Private Chat Guard
        if chat_type != "private":
            await tg_client.send_message(
                chat_id=chat_id,
                text=messages.private_chat_only_message(),
            )
            return {"ok": True, "action": "non_private_rejected"}

        # 2. Resolve Actor Role
        admin_repo = ClientBotAdminRepository(session)
        admin_record = await admin_repo.get_by_bot_and_telegram_user(
            client_bot_id=self.bot.id,
            telegram_user_id=user_id,
        )
        is_admin = bool(admin_record and admin_record.is_active)
        role = "ADMIN" if is_admin else "VIEWER"

        actor = ClientBotActorContext(
            telegram_user_id=user_id,
            chat_id=chat_id,
            chat_type=chat_type,
            username=actor_data.get("username"),
            first_name=actor_data.get("first_name"),
            last_name=actor_data.get("last_name"),
            language_code=actor_data.get("language_code"),
            role=role,
            admin_record_id=admin_record.id if admin_record else None,
        )

        bot_ctx = ClientBotContext(
            client_bot_id=self.bot.id,
            client_id=self.bot.client_id,
            telegram_bot_id=self.bot.telegram_bot_id,
            bot_username=self.bot.username,
            display_name=self.bot.display_name,
            status=self.bot.status,
            public_bot_id=self.bot.public_id,
        )

        # 3. Status Guard Handling
        if raw_status == ClientBotStatus.PAUSED.value:
            paused_text = (
                messages.bot_paused_admin_message(self.bot.username)
                if is_admin
                else messages.bot_paused_viewer_message()
            )
            await tg_client.send_message(chat_id=chat_id, text=paused_text)
            return {"ok": True, "action": "bot_paused"}

        if raw_status not in (ClientBotStatus.ACTIVE.value,):
            await tg_client.send_message(
                chat_id=chat_id,
                text=messages.bot_inactive_message(),
            )
            return {"ok": True, "action": "bot_inactive"}

        # 4. Route based on role
        if is_admin:
            admin_router = ClientAdminRouter(telegram_client=tg_client)
            return await admin_router.handle(bot_ctx, actor, actor_data, session)

        # 5. For Normal Viewers: Check for Admin Command Attempt
        cmd = text.lower().split()[0] if text.startswith("/") else ""
        if cmd in ADMIN_COMMANDS:
            await tg_client.send_message(
                chat_id=chat_id,
                text=messages.admin_only_command_message(),
            )
            return {"ok": True, "action": "admin_command_rejected_for_viewer"}

        # 6. Route to Viewer Router
        viewer_router = ClientViewerRouter(telegram_client=tg_client)
        return await viewer_router.handle(bot_ctx, actor, actor_data, session)
