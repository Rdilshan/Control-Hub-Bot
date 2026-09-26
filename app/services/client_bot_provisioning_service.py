"""Client Bot Provisioning Service handling webhook configuration and command menu setup."""

import secrets
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.enums import (
    BotAdminRole,
    BotEventType,
    ClientBotStatus,
    JobStatus,
    JobType,
    enum_val,
)
from app.core.utils import utc_now
from app.db.models.client_bot import ClientBot
from app.logging_config import get_logger
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.repositories.client_bot_admin import ClientBotAdminRepository
from app.repositories.event import BotEventRepository
from app.repositories.job import BackgroundJobRepository
from app.services.bot_token_encryption_service import BotTokenEncryptionService
from app.telegram.client import TelegramClient
from app.telegram.errors import (
    TelegramAPIError,
    TelegramInvalidTokenError,
    TelegramNetworkError,
)

logger = get_logger(__name__)

# Standard Command Scopes
NORMAL_USER_COMMANDS = [
    {"command": "start", "description": "Start the bot"},
    {"command": "help", "description": "Help & information"},
]

OWNER_ADMIN_COMMANDS = [
    {"command": "createvideo", "description": "Create new video post"},
    {"command": "createcollection", "description": "Create a video collection"},
    {"command": "stats", "description": "View bot analytics"},
    {"command": "videos", "description": "Manage videos"},
    {"command": "processing", "description": "Processing queue"},
    {"command": "users", "description": "Viewer management"},
    {"command": "broadcasts", "description": "Broadcast campaigns"},
    {"command": "sponsor", "description": "Sponsor configuration"},
    {"command": "startmessage", "description": "Edit start message"},
    {"command": "defaultmessage", "description": "Edit default reply"},
]


class ClientBotProvisioningService:
    """Manages Telegram bot runtime provisioning: webhooks, secrets, command scopes, and activation."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.bot_repo = ClientBotRepository(session)
        self.admin_repo = ClientBotAdminRepository(session)
        self.event_repo = BotEventRepository(session)
        self.job_repo = BackgroundJobRepository(session)
        self.client_repo = ClientRepository(session)
        self.encryption_service = BotTokenEncryptionService()

    async def provision_bot(
        self,
        client_bot_id: int,
        client_id: int,
        http_client: Optional[Any] = None,
    ) -> Tuple[bool, str]:
        """Provisions a connected Telegram bot: validates token, sets webhook, and configures command menus."""
        settings = get_settings()

        # 1. Fetch Client Bot with multi-tenant verification
        bot = await self.bot_repo.get_by_id_and_client(bot_id=client_bot_id, client_id=client_id)
        if not bot:
            logger.warning(f"Provisioning rejected: Bot #{client_bot_id} not found for client #{client_id}")
            return False, "Bot not found or access denied"

        # 2. Check client status
        client = await self.client_repo.get_by_id(client_id)
        if not client or enum_val(client.status) != "ACTIVE":
            logger.warning(f"Provisioning halted: Client #{client_id} is not active")
            return False, "Client account is not active"

        # 3. Decrypt token
        raw_token = self.encryption_service.decrypt_token(bot.token_encrypted)
        if not raw_token:
            bot.status = ClientBotStatus.INVALID_TOKEN
            await self.session.flush()
            return False, "Bot token is missing or could not be decrypted"

        tg_client = TelegramClient(token=raw_token, http_client=http_client)

        try:
            # 4. Verify identity via getMe
            bot_info = await tg_client.get_me()
            bot.username = bot_info.username
            bot.display_name = bot_info.first_name

            # 5. Generate public ID if not present
            if not bot.public_id:
                bot.public_id = f"b_{secrets.token_hex(6)}"

            # 6. Generate secure webhook secret
            plain_secret = secrets.token_urlsafe(32)
            bot.webhook_secret_encrypted = self.encryption_service.encrypt_token(plain_secret)

            # 7. Configure Telegram Webhook
            base_webhook_url = (settings.TELEGRAM_WEBHOOK_BASE_URL or "https://api.controlhub.local").rstrip("/")
            webhook_url = f"{base_webhook_url}/api/v1/webhooks/telegram/client/{bot.public_id}"

            await tg_client.set_webhook(
                url=webhook_url,
                secret_token=plain_secret,
                allowed_updates=["message", "callback_query", "my_chat_member"],
                drop_pending_updates=False,
            )

            # 8. Configure Normal-User Command Menu (default scope)
            await tg_client.set_my_commands(
                commands=NORMAL_USER_COMMANDS,
                scope={"type": "default"},
            )

            # 9. Configure Owner-Only Command Menu (chat scope for owner)
            admins = await self.admin_repo.list_by_bot(client_bot_id=bot.id)
            owner_admin = next((a for a in admins if a.role == BotAdminRole.OWNER), None)
            if owner_admin:
                await tg_client.set_my_commands(
                    commands=OWNER_ADMIN_COMMANDS,
                    scope={"type": "chat", "chat_id": owner_admin.telegram_user_id},
                )

            # 10. Mark bot ACTIVE
            bot.status = ClientBotStatus.ACTIVE
            bot.connected_at = utc_now()
            bot.last_verified_at = utc_now()
            bot.disconnected_at = None

            # 11. Record event
            await self.event_repo.record_event(
                client_bot_id=bot.id,
                event_type=BotEventType.BOT_CONNECTED,
                telegram_user_id=owner_admin.telegram_user_id if owner_admin else None,
                metadata_json={
                    "username": bot.username,
                    "telegram_bot_id": bot.telegram_bot_id,
                    "public_id": bot.public_id,
                },
            )

            await self.session.flush()
            logger.info(f"Bot #{bot.id} (@{bot.username}) successfully provisioned for client #{client_id}")
            return True, "Bot provisioned successfully"

        except TelegramNetworkError as exc:
            bot.status = ClientBotStatus.PROVISION_FAILED
            await self.event_repo.record_event(
                client_bot_id=bot.id,
                event_type=BotEventType.BOT_CONNECTION_FAILED,
                metadata_json={"error": "NETWORK_ERROR", "description": str(exc)},
            )
            await self.session.flush()
            logger.error(f"Network failure provisioning bot #{bot.id}: {exc}")
            return False, "Telegram is currently unreachable. Please try again."
        except (TelegramInvalidTokenError, TelegramAPIError) as exc:
            bot.status = ClientBotStatus.PROVISION_FAILED
            await self.event_repo.record_event(
                client_bot_id=bot.id,
                event_type=BotEventType.BOT_CONNECTION_FAILED,
                metadata_json={"error": "API_ERROR", "description": str(exc)},
            )
            await self.session.flush()
            logger.error(f"Provisioning failed for bot #{bot.id}: {exc}")
            return False, f"Telegram API error: {exc}"
        except Exception as exc:
            bot.status = ClientBotStatus.PROVISION_FAILED
            await self.session.flush()
            logger.exception(f"Unexpected error provisioning bot #{bot.id}: {exc}")
            return False, f"Provisioning failed: {exc}"

    async def disconnect_bot(
        self,
        client_bot_id: int,
        client_id: int,
        http_client: Optional[Any] = None,
    ) -> Tuple[bool, str]:
        """Gracefully disconnects a client bot, deletes webhook, and cleans up active credentials."""
        bot = await self.bot_repo.get_by_id_and_client(bot_id=client_bot_id, client_id=client_id)
        if not bot:
            return False, "Bot not found or access denied"

        # 1. Attempt webhook deletion via Telegram if token exists
        raw_token = self.encryption_service.decrypt_token(bot.token_encrypted)
        if raw_token:
            tg_client = TelegramClient(token=raw_token, http_client=http_client)
            try:
                await tg_client.delete_webhook(drop_pending_updates=False)
            except Exception as exc:
                logger.warning(f"Could not remove webhook from Telegram for bot #{bot.id}: {exc}")

        # 2. Update status and clear active token
        bot.status = ClientBotStatus.DISCONNECTED
        bot.disconnected_at = utc_now()
        bot.token_encrypted = None
        bot.webhook_secret_encrypted = None

        # 3. Record event
        await self.event_repo.record_event(
            client_bot_id=bot.id,
            event_type=BotEventType.BOT_DISCONNECTED,
            metadata_json={"disconnected_at": bot.disconnected_at.isoformat()},
        )

        await self.session.flush()
        logger.info(f"Bot #{bot.id} disconnected successfully by client #{client_id}")
        return True, "Bot disconnected successfully"
