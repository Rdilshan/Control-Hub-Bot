"""Client Bot Health Service for token verification, webhook audit, and lifecycle reconciliation."""

from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    BotEventType,
    ClientBotStatus,
    enum_val,
)
from app.core.utils import utc_now
from app.db.models.client_bot import ClientBot
from app.logging_config import logger
from app.repositories.client_bot import ClientBotRepository
from app.repositories.event import BotEventRepository
from app.services.bot_token_encryption_service import BotTokenEncryptionService
from app.services.client_bot_lifecycle_service import ClientBotLifecycleService
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramInvalidTokenError, TelegramNetworkError


class ClientBotHealthService:
    """Performs non-intrusive health checks and lifecycle state reconciliation across client bots."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.bot_repo = ClientBotRepository(session)
        self.event_repo = BotEventRepository(session)
        self.encryption_service = BotTokenEncryptionService()
        self.lifecycle_service = ClientBotLifecycleService(session)

    async def check_bot_health(
        self,
        client_bot_id: int,
        http_client: Optional[Any] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Verifies Telegram bot token validity without modifying active business flow unless unauthorized."""
        bot = await self.bot_repo.get_by_id(client_bot_id)
        if not bot:
            return False, "Bot not found", {}

        curr_status = enum_val(bot.status)
        if curr_status == ClientBotStatus.DISCONNECTED.value:
            return True, "Bot is disconnected", {"status": curr_status}

        raw_token = self.encryption_service.decrypt_token(bot.token_encrypted)
        if not raw_token:
            await self.lifecycle_service.mark_invalid_token(bot.id, reason="TOKEN_MISSING")
            return False, "Bot token missing", {"status": ClientBotStatus.INVALID_TOKEN.value}

        tg_client = TelegramClient(token=raw_token, http_client=http_client)
        try:
            bot_info = await tg_client.get_me()
            bot.last_verified_at = utc_now()

            # If bot was UNAVAILABLE, recover state
            if curr_status == ClientBotStatus.UNAVAILABLE.value:
                target_status = bot.desired_status or ClientBotStatus.ACTIVE.value
                bot.status = ClientBotStatus(target_status)
                bot.desired_status = None
                bot.status_reason = "RECOVERED_HEALTH_CHECK"
                bot.last_status_changed_at = utc_now()
                bot.lifecycle_version = (bot.lifecycle_version or 0) + 1

                await self.event_repo.record_event(
                    client_bot_id=bot.id,
                    event_type=BotEventType.BOT_RESUMED,
                    metadata_json={"recovered_status": target_status},
                )
                await self.lifecycle_service.resume_bot_work(bot.id)

            await self.session.flush()
            return True, "Bot is healthy", {
                "username": bot_info.username,
                "telegram_bot_id": bot_info.id,
                "status": enum_val(bot.status),
            }

        except TelegramInvalidTokenError:
            logger.warning(f"Health check detected invalid token for bot #{bot.id}")
            await self.lifecycle_service.mark_invalid_token(bot.id, reason="TELEGRAM_401_UNAUTHORIZED")
            return False, "Bot token is invalid", {"status": ClientBotStatus.INVALID_TOKEN.value}

        except TelegramNetworkError as exc:
            logger.warning(f"Transient network error during health check for bot #{bot.id}: {exc}")
            # Do NOT mark INVALID_TOKEN on network timeouts
            return False, "Telegram network error", {"status": "NETWORK_ERROR", "error": str(exc)}

        except Exception as exc:
            logger.error(f"Unexpected error during health check for bot #{bot.id}: {exc}")
            return False, f"Health check failed: {exc}", {"error": str(exc)}

    async def reconcile_lifecycle(self, http_client: Optional[Any] = None) -> Dict[str, int]:
        """Reconciles stale intermediate lifecycle states across all bots."""
        # 1. Stale DISCONNECTING bots
        stmt_disc = select(ClientBot).where(ClientBot.status == ClientBotStatus.DISCONNECTING)
        res_disc = await self.session.execute(stmt_disc)
        stale_disconnecting = res_disc.scalars().all()

        reconciled_disc = 0
        for b in stale_disconnecting:
            success, _ = await self.lifecycle_service.complete_disconnect(b.id, http_client=http_client)
            if success:
                reconciled_disc += 1

        await self.session.flush()
        return {
            "reconciled_disconnecting": reconciled_disc,
        }
