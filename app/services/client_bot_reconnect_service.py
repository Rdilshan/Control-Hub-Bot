"""Client Bot Reconnect Service for re-attaching credentials and restoring active management."""

import re
import secrets
from typing import Any, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.enums import (
    BotAdminRole,
    BotEventType,
    ClientBotStatus,
    enum_val,
)
from app.core.utils import utc_now
from app.db.models.client_bot import ClientBot
from app.logging_config import logger
from app.repositories.client_bot import ClientBotRepository
from app.repositories.client_bot_admin import ClientBotAdminRepository
from app.repositories.event import BotEventRepository
from app.services.bot_token_encryption_service import BotTokenEncryptionService
from app.services.client_bot_lifecycle_service import ClientBotLifecycleService
from app.services.client_bot_provisioning_service import (
    NORMAL_USER_COMMANDS,
    OWNER_ADMIN_COMMANDS,
)
from app.telegram.client import TelegramClient
from app.telegram.errors import (
    TelegramAPIError,
    TelegramInvalidTokenError,
    TelegramNetworkError,
)

BOT_TOKEN_REGEX = re.compile(r"^\d{6,14}:[A-Za-z0-9_-]{30,60}$")


class ClientBotReconnectService:
    """Handles secure reconnection of disconnected, invalid, or revoked Client Bots."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.bot_repo = ClientBotRepository(session)
        self.admin_repo = ClientBotAdminRepository(session)
        self.event_repo = BotEventRepository(session)
        self.encryption_service = BotTokenEncryptionService()
        self.lifecycle_service = ClientBotLifecycleService(session)

    def validate_token_format(self, token: str) -> bool:
        """Validates token format against standard Telegram BotFather token pattern."""
        if not token:
            return False
        return bool(BOT_TOKEN_REGEX.match(token.strip()))

    async def reconnect_bot(
        self,
        client_bot_id: int,
        client_id: int,
        token: str,
        http_client: Optional[Any] = None,
    ) -> Tuple[bool, str, Optional[ClientBot]]:
        """Re-establishes bot webhook, credentials, and resumes operations for the exact same Telegram bot ID."""
        settings = get_settings()
        clean_token = token.strip() if token else ""

        # 1. Validate token format
        if not self.validate_token_format(clean_token):
            return False, "Invalid token format. Please check the token from BotFather.", None

        # 2. Fetch existing bot and verify client ownership
        bot = await self.bot_repo.get_by_id_and_client(bot_id=client_bot_id, client_id=client_id)
        if not bot:
            return False, "Bot not found or access denied", None

        # 3. Verify Telegram credentials via getMe
        tg_client = TelegramClient(token=clean_token, http_client=http_client)
        try:
            bot_info = await tg_client.get_me()
        except TelegramInvalidTokenError:
            return False, "Telegram rejected this token as invalid.", None
        except TelegramNetworkError as exc:
            logger.error(f"Network error during reconnect for bot #{bot.id}: {exc}")
            return False, "Telegram service is currently unreachable. Please try again later.", None
        except Exception as exc:
            logger.error(f"Telegram error validating reconnect token for bot #{bot.id}: {exc}")
            return False, f"Could not verify token with Telegram: {exc}", None

        # 4. CRITICAL IDENTITY CHECK: Verify telegram_bot_id matches
        if bot_info.id != bot.telegram_bot_id:
            logger.warning(
                f"Reconnect rejected for bot #{bot.id}: Token belongs to bot ID {bot_info.id} "
                f"(@{bot_info.username}), expected {bot.telegram_bot_id} (@{bot.username})"
            )
            return (
                False,
                f"This token belongs to @{bot_info.username} (ID: {bot_info.id}). "
                f"You must provide a token for the existing bot @{bot.username}.",
                None,
            )

        # 5. Encrypt new token and generate fresh webhook secret
        bot.token_encrypted = self.encryption_service.encrypt_token(clean_token)
        plain_secret = secrets.token_urlsafe(32)
        bot.webhook_secret_encrypted = self.encryption_service.encrypt_token(plain_secret)
        bot.username = bot_info.username
        bot.display_name = bot_info.first_name

        # Ensure public_id exists
        if not bot.public_id:
            bot.public_id = f"b_{secrets.token_hex(6)}"

        # 6. Configure Telegram Webhook
        base_webhook_url = (settings.TELEGRAM_WEBHOOK_BASE_URL or "https://api.controlhub.local").rstrip("/")
        webhook_url = f"{base_webhook_url}/api/v1/webhooks/telegram/client/{bot.public_id}"

        try:
            await tg_client.set_webhook(
                url=webhook_url,
                secret_token=plain_secret,
                allowed_updates=["message", "callback_query", "my_chat_member"],
                drop_pending_updates=False,
            )

            # 7. Configure command scopes
            await tg_client.set_my_commands(
                commands=NORMAL_USER_COMMANDS,
                scope={"type": "default"},
            )

            admins = await self.admin_repo.list_by_bot(client_bot_id=bot.id)
            owner_admin = next((a for a in admins if a.role == BotAdminRole.OWNER), None)
            if owner_admin:
                await tg_client.set_my_commands(
                    commands=OWNER_ADMIN_COMMANDS,
                    scope={"type": "chat", "chat_id": owner_admin.telegram_user_id},
                )
        except Exception as exc:
            logger.error(f"Failed to configure webhook/commands on reconnect for bot #{bot.id}: {exc}")
            return False, f"Could not configure Telegram webhook: {exc}", None

        # 8. Restore ACTIVE state
        bot.status = ClientBotStatus.ACTIVE
        bot.disconnected_at = None
        bot.paused_at = None
        bot.status_reason = "CLIENT_RECONNECTED"
        bot.last_status_changed_at = utc_now()
        bot.last_verified_at = utc_now()
        bot.lifecycle_version = (bot.lifecycle_version or 0) + 1

        # 9. Record event
        await self.event_repo.record_event(
            client_bot_id=bot.id,
            event_type=BotEventType.BOT_RECONNECTED,
            metadata_json={
                "username": bot.username,
                "telegram_bot_id": bot.telegram_bot_id,
                "reconnected_at": utc_now().isoformat(),
            },
        )

        # 10. Resume pending work
        await self.lifecycle_service.resume_bot_work(bot.id)

        await self.session.flush()
        logger.info(f"Bot #{bot.id} (@{bot.username}) successfully reconnected by client #{client_id}")
        return True, "Bot reconnected successfully", bot
