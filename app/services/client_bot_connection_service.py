"""Client Bot Connection Service managing validation, duplicate checks, session tokens, and connections."""

import json
import re
import secrets
from typing import Any, Dict, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BotEventType, ClientBotStatus, enum_val
from app.core.utils import utc_now
from app.db.models.client_bot import ClientBot
from app.logging_config import get_logger
from app.redis.client import get_redis
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.repositories.event import BotEventRepository
from app.services.bot_token_encryption_service import BotTokenEncryptionService
from app.services.client_bot_provisioning_service import ClientBotProvisioningService
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramInvalidTokenError, TelegramNetworkError
from app.telegram.types import TelegramBotInfo

logger = get_logger(__name__)

PENDING_CONN_PREFIX = "controlhub:pending_conn:"
PENDING_CONN_TTL = 600  # 10 minutes

# In-memory fallback for pending connection sessions
_in_memory_pending_store: Dict[str, str] = {}

TOKEN_REGEX = re.compile(r"^\d{6,14}:[A-Za-z0-9_-]{30,60}$")


class ClientBotConnectionService:
    """Orchestrates Telegram bot token intake, validation, ownership verification, and connection."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.client_repo = ClientRepository(session)
        self.bot_repo = ClientBotRepository(session)
        self.event_repo = BotEventRepository(session)
        self.encryption_service = BotTokenEncryptionService()
        self.provisioning_service = ClientBotProvisioningService(session)

    # --- 1. Token Validation ---

    async def validate_token(
        self,
        raw_token: str,
        http_client: Optional[Any] = None,
    ) -> Tuple[bool, Optional[TelegramBotInfo], Optional[str], bool]:
        """Validates a bot token against Telegram's API getMe.
        
        Returns:
            (is_valid, bot_info, error_message, is_network_error)
        """
        clean_token = raw_token.strip()
        if not clean_token or not TOKEN_REGEX.match(clean_token):
            return False, None, "Invalid token format. Tokens look like 123456789:ABCDEF...", False

        tg_client = TelegramClient(token=clean_token, http_client=http_client)
        try:
            bot_info = await tg_client.get_me()
            return True, bot_info, None, False
        except TelegramInvalidTokenError as exc:
            logger.info("Bot token validation failed: Invalid token")
            return False, None, f"Invalid Bot Token: {exc.message}", False
        except TelegramNetworkError as exc:
            logger.warning(f"Bot token validation failed due to network error: {exc}")
            return False, None, "Telegram could not be reached right now. Please try again.", True
        except Exception as exc:
            logger.error(f"Unexpected error during token validation: {exc}")
            return False, None, "Failed to validate token with Telegram.", False

    # --- 2. Duplicate & Ownership Checks ---

    async def check_bot_ownership(
        self,
        telegram_bot_id: int,
        client_id: int,
    ) -> Tuple[str, Optional[ClientBot]]:
        """Determines the connection state for a given Telegram bot ID.
        
        Returns:
            ("NEW", None)
            ("ALREADY_CONNECTED", existing_bot)
            ("RECONNECT", existing_bot)
            ("OTHER_OWNER", None)
        """
        existing_bot = await self.bot_repo.get_by_telegram_bot_id(telegram_bot_id)
        if not existing_bot:
            return "NEW", None

        if existing_bot.client_id == client_id:
            raw_status = enum_val(existing_bot.status)
            if raw_status in (ClientBotStatus.ACTIVE.value, ClientBotStatus.PAUSED.value):
                return "ALREADY_CONNECTED", existing_bot
            else:
                return "RECONNECT", existing_bot

        # Owned by a different client
        return "OTHER_OWNER", None

    # --- 3. Temporary Validated Session Management ---

    async def prepare_pending_connection(
        self,
        client_id: int,
        raw_token: str,
        bot_info: TelegramBotInfo,
        reconnect_bot_id: Optional[int] = None,
    ) -> str:
        """Stores temporary validated bot credentials in Redis with encrypted token."""
        temp_id = secrets.token_urlsafe(16)
        encrypted_token = self.encryption_service.encrypt_token(raw_token.strip())

        payload = {
            "client_id": client_id,
            "telegram_bot_id": bot_info.id,
            "username": bot_info.username,
            "display_name": bot_info.first_name,
            "encrypted_token": encrypted_token,
            "reconnect_bot_id": reconnect_bot_id,
            "created_at": utc_now().isoformat(),
        }

        try:
            redis = get_redis()
            await redis.set(
                f"{PENDING_CONN_PREFIX}{temp_id}",
                json.dumps(payload),
                ex=PENDING_CONN_TTL,
            )
        except Exception:
            _in_memory_pending_store[temp_id] = json.dumps(payload)

        return temp_id

    async def get_pending_connection(self, temp_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves pending connection details by temporary session ID."""
        raw = None
        try:
            redis = get_redis()
            raw = await redis.get(f"{PENDING_CONN_PREFIX}{temp_id}")
        except Exception:
            pass

        if not raw:
            raw = _in_memory_pending_store.get(temp_id)

        if not raw:
            return None

        try:
            return json.loads(raw)
        except Exception:
            return None

    async def clear_pending_connection(self, temp_id: str) -> None:
        """Deletes temporary pending connection session."""
        try:
            redis = get_redis()
            await redis.delete(f"{PENDING_CONN_PREFIX}{temp_id}")
        except Exception:
            pass
        _in_memory_pending_store.pop(temp_id, None)

    # --- 4. Confirm and Provision Connection ---

    async def confirm_connection(
        self,
        client_id: int,
        temp_id: str,
        http_client: Optional[Any] = None,
    ) -> Tuple[bool, str, Optional[ClientBot]]:
        """Confirms pending connection, creates/updates database records, and executes provisioning."""
        pending = await self.get_pending_connection(temp_id)
        if not pending or pending.get("client_id") != client_id:
            return False, "Connection session expired or invalid. Please try connecting again.", None

        client = await self.client_repo.get_by_id(client_id)
        if not client or enum_val(client.status) != "ACTIVE":
            return False, "Your account is not active.", None

        reconnect_bot_id = pending.get("reconnect_bot_id")
        bot: Optional[ClientBot] = None

        if reconnect_bot_id:
            # Reconnection Flow
            bot = await self.bot_repo.get_by_id_and_client(bot_id=reconnect_bot_id, client_id=client_id)
            if not bot or bot.telegram_bot_id != pending["telegram_bot_id"]:
                return False, "This token belongs to a different bot than the one being reconnected.", None

            bot.token_encrypted = pending["encrypted_token"]
            bot.username = pending["username"]
            bot.display_name = pending["display_name"]
            bot.status = ClientBotStatus.PROVISIONING
            bot.disconnected_at = None
            bot.last_verified_at = utc_now()
            await self.session.flush()

            await self.event_repo.record_event(
                client_bot_id=bot.id,
                event_type=BotEventType.BOT_RECONNECTED,
                telegram_user_id=client.telegram_user_id,
                metadata_json={"username": bot.username},
            )
        else:
            # New Connection Flow
            raw_token = self.encryption_service.decrypt_token(pending["encrypted_token"])
            bot = await self.bot_repo.create_with_defaults(
                client_id=client_id,
                telegram_bot_id=pending["telegram_bot_id"],
                token=raw_token or "",
                username=pending["username"],
                display_name=pending["display_name"],
                owner_telegram_user_id=client.telegram_user_id,
                owner_username=client.username,
                owner_first_name=client.first_name,
            )
            bot.status = ClientBotStatus.PROVISIONING
            bot.public_id = f"b_{secrets.token_hex(6)}"
            await self.session.flush()

            await self.event_repo.record_event(
                client_bot_id=bot.id,
                event_type=BotEventType.BOT_CONNECTION_STARTED,
                telegram_user_id=client.telegram_user_id,
                metadata_json={"username": bot.username, "public_id": bot.public_id},
            )

        # Execute Provisioning
        prov_ok, prov_msg = await self.provisioning_service.provision_bot(
            client_bot_id=bot.id,
            client_id=client_id,
            http_client=http_client,
        )

        # Clear session
        await self.clear_pending_connection(temp_id)

        if not prov_ok:
            return False, prov_msg, bot

        return True, "Bot connected successfully!", bot

    async def retry_provisioning(
        self,
        client_bot_id: int,
        client_id: int,
        http_client: Optional[Any] = None,
    ) -> Tuple[bool, str]:
        """Retries provisioning for an existing bot without requiring token re-entry."""
        bot = await self.bot_repo.get_by_id_and_client(bot_id=client_bot_id, client_id=client_id)
        if not bot:
            return False, "Bot not found or access denied"

        bot.status = ClientBotStatus.PROVISIONING
        await self.session.flush()

        return await self.provisioning_service.provision_bot(
            client_bot_id=client_bot_id,
            client_id=client_id,
            http_client=http_client,
        )
