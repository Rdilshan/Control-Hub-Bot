"""Client Bot Lifecycle Service for managing state transitions, pauses, resumes, and disconnects."""

from typing import Any, Dict, Optional, Set, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    BotEventType,
    BroadcastStatus,
    CatchupStatus,
    ClientBotStatus,
    JobType,
    enum_val,
)
from app.core.security import decrypt_token, encrypt_token
from app.core.utils import utc_now
from app.db.models.broadcast import Broadcast
from app.db.models.client_bot import ClientBot
from app.db.models.viewer_catchup import ViewerCatchup
from app.logging_config import logger
from app.repositories.client_bot import ClientBotRepository
from app.repositories.event import BotEventRepository
from app.repositories.job import BackgroundJobRepository
from app.services.bot_token_encryption_service import BotTokenEncryptionService
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramInvalidTokenError, TelegramNetworkError


VALID_TRANSITIONS: Dict[str, Set[str]] = {
    ClientBotStatus.PROVISIONING.value: {
        ClientBotStatus.ACTIVE.value,
        ClientBotStatus.PROVISION_FAILED.value,
        ClientBotStatus.DISCONNECTED.value,
    },
    ClientBotStatus.ACTIVE.value: {
        ClientBotStatus.PAUSED.value,
        ClientBotStatus.DISCONNECTING.value,
        ClientBotStatus.DISCONNECTED.value,
        ClientBotStatus.INVALID_TOKEN.value,
        ClientBotStatus.UNAVAILABLE.value,
        ClientBotStatus.REVOKED.value,
    },
    ClientBotStatus.PAUSED.value: {
        ClientBotStatus.ACTIVE.value,
        ClientBotStatus.DISCONNECTING.value,
        ClientBotStatus.DISCONNECTED.value,
        ClientBotStatus.INVALID_TOKEN.value,
        ClientBotStatus.UNAVAILABLE.value,
        ClientBotStatus.REVOKED.value,
    },
    ClientBotStatus.DISCONNECTING.value: {
        ClientBotStatus.DISCONNECTED.value,
        ClientBotStatus.ACTIVE.value,
        ClientBotStatus.UNAVAILABLE.value,
    },
    ClientBotStatus.DISCONNECTED.value: {
        ClientBotStatus.PROVISIONING.value,
        ClientBotStatus.ACTIVE.value,
    },
    ClientBotStatus.INVALID_TOKEN.value: {
        ClientBotStatus.PROVISIONING.value,
        ClientBotStatus.ACTIVE.value,
        ClientBotStatus.DISCONNECTED.value,
    },
    ClientBotStatus.UNAVAILABLE.value: {
        ClientBotStatus.ACTIVE.value,
        ClientBotStatus.PAUSED.value,
        ClientBotStatus.INVALID_TOKEN.value,
        ClientBotStatus.REVOKED.value,
        ClientBotStatus.DISCONNECTED.value,
    },
    ClientBotStatus.REVOKED.value: {
        ClientBotStatus.PROVISIONING.value,
        ClientBotStatus.ACTIVE.value,
        ClientBotStatus.DISCONNECTED.value,
    },
    ClientBotStatus.PROVISION_FAILED.value: {
        ClientBotStatus.PROVISIONING.value,
        ClientBotStatus.ACTIVE.value,
        ClientBotStatus.DISCONNECTED.value,
    },
}


class ClientBotLifecycleService:
    """Manages explicit lifecycle state transitions for Client Bots with audit logging and worker coordination."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.bot_repo = ClientBotRepository(session)
        self.event_repo = BotEventRepository(session)
        self.job_repo = BackgroundJobRepository(session)
        self.encryption_service = BotTokenEncryptionService()

    def is_transition_valid(self, current_status: object, target_status: object) -> bool:
        """Validates whether a lifecycle state transition is allowable."""
        curr_str = enum_val(current_status)
        target_str = enum_val(target_status)
        if curr_str == target_str:
            return True
        allowed = VALID_TRANSITIONS.get(curr_str, set())
        return target_str in allowed

    async def pause_bot(
        self,
        client_bot_id: int,
        client_id: int,
        reason: str = "CLIENT_PAUSED",
    ) -> Tuple[bool, str, Optional[ClientBot]]:
        """Pauses an ACTIVE client bot, pausing active broadcasts and catch-up jobs while preserving data."""
        bot = await self.bot_repo.get_by_id_and_client(bot_id=client_bot_id, client_id=client_id)
        if not bot:
            return False, "Bot not found or access denied", None

        curr_status = enum_val(bot.status)
        if curr_status == ClientBotStatus.PAUSED.value:
            return True, "Bot is already paused", bot

        if curr_status != ClientBotStatus.ACTIVE.value:
            return False, f"Cannot pause bot in {curr_status} status", None

        # Update bot record
        bot.status = ClientBotStatus.PAUSED
        bot.paused_at = utc_now()
        bot.status_reason = reason
        bot.last_status_changed_at = utc_now()
        bot.lifecycle_version = (bot.lifecycle_version or 0) + 1

        # Record audit event
        await self.event_repo.record_event(
            client_bot_id=bot.id,
            event_type=BotEventType.BOT_PAUSED,
            metadata_json={"paused_at": bot.paused_at.isoformat(), "reason": reason},
        )

        # Pause any running live broadcasts for this bot
        stmt_bc = (
            select(Broadcast)
            .where(
                Broadcast.client_bot_id == bot.id,
                Broadcast.status.in_([BroadcastStatus.RUNNING, BroadcastStatus.QUEUED]),
            )
        )
        res_bc = await self.session.execute(stmt_bc)
        for bc in res_bc.scalars().all():
            bc.status = BroadcastStatus.PAUSED

        await self.session.flush()
        logger.info(f"Bot #{bot.id} (@{bot.username}) successfully paused (reason={reason})")
        return True, "Bot paused successfully", bot

    async def resume_bot(
        self,
        client_bot_id: int,
        client_id: int,
        http_client: Optional[Any] = None,
    ) -> Tuple[bool, str, Optional[ClientBot]]:
        """Resumes a PAUSED or UNAVAILABLE client bot after verifying credentials."""
        bot = await self.bot_repo.get_by_id_and_client(bot_id=client_bot_id, client_id=client_id)
        if not bot:
            return False, "Bot not found or access denied", None

        curr_status = enum_val(bot.status)
        if curr_status == ClientBotStatus.ACTIVE.value:
            return True, "Bot is already active", bot

        if curr_status not in (ClientBotStatus.PAUSED.value, ClientBotStatus.UNAVAILABLE.value):
            return False, f"Cannot resume bot from {curr_status} status. Please reconnect if needed.", None

        # Verify bot token with Telegram
        raw_token = self.encryption_service.decrypt_token(bot.token_encrypted)
        if not raw_token:
            await self.mark_invalid_token(bot.id, reason="TOKEN_MISSING_ON_RESUME")
            return False, "Bot token is missing or corrupted. Please reconnect.", bot

        tg_client = TelegramClient(token=raw_token, http_client=http_client)
        try:
            bot_info = await tg_client.get_me()
            bot.username = bot_info.username
            bot.display_name = bot_info.first_name
        except TelegramInvalidTokenError:
            await self.mark_invalid_token(bot.id, reason="TOKEN_UNAUTHORIZED_ON_RESUME")
            return False, "Bot token is no longer valid. Please reconnect with a fresh token.", bot
        except TelegramNetworkError as exc:
            logger.warning(f"Network issue verifying bot #{bot.id} on resume: {exc}")
            # Do not mark INVALID_TOKEN on transient network error

        # Set ACTIVE
        bot.status = ClientBotStatus.ACTIVE
        bot.paused_at = None
        bot.status_reason = "CLIENT_RESUMED"
        bot.last_status_changed_at = utc_now()
        bot.last_verified_at = utc_now()
        bot.lifecycle_version = (bot.lifecycle_version or 0) + 1

        # Audit event
        await self.event_repo.record_event(
            client_bot_id=bot.id,
            event_type=BotEventType.BOT_RESUMED,
            metadata_json={"resumed_at": utc_now().isoformat()},
        )

        # Enqueue resume work job
        await self.job_repo.create_job(
            job_type=JobType.CLIENT_BOT_RESUME_WORK,
            client_bot_id=bot.id,
            payload={"client_bot_id": bot.id},
        )

        # Resume paused broadcasts directly
        await self.resume_bot_work(bot.id)

        await self.session.flush()
        logger.info(f"Bot #{bot.id} (@{bot.username}) resumed successfully")
        return True, "Bot resumed successfully", bot

    async def begin_disconnect(
        self,
        client_bot_id: int,
        client_id: int,
    ) -> Tuple[bool, str, Optional[ClientBot]]:
        """Initiates graceful disconnection for a Client Bot."""
        bot = await self.bot_repo.get_by_id_and_client(bot_id=client_bot_id, client_id=client_id)
        if not bot:
            return False, "Bot not found or access denied", None

        curr_status = enum_val(bot.status)
        if curr_status == ClientBotStatus.DISCONNECTED.value:
            return True, "Bot is already disconnected", bot

        if curr_status == ClientBotStatus.DISCONNECTING.value:
            return True, "Disconnect is already in progress", bot

        bot.status = ClientBotStatus.DISCONNECTING
        bot.status_reason = "CLIENT_DISCONNECT_REQUESTED"
        bot.last_status_changed_at = utc_now()
        bot.lifecycle_version = (bot.lifecycle_version or 0) + 1

        await self.event_repo.record_event(
            client_bot_id=bot.id,
            event_type=BotEventType.BOT_DISCONNECT_STARTED,
            metadata_json={"started_at": utc_now().isoformat()},
        )

        # Enqueue disconnect job
        await self.job_repo.create_job(
            job_type=JobType.CLIENT_BOT_DISCONNECT,
            client_bot_id=bot.id,
            payload={"client_bot_id": bot.id, "client_id": client_id},
        )

        await self.session.flush()
        logger.info(f"Disconnect initiated for bot #{bot.id} (@{bot.username})")
        return True, "Disconnect initiated", bot

    async def complete_disconnect(
        self,
        client_bot_id: int,
        http_client: Optional[Any] = None,
    ) -> Tuple[bool, str]:
        """Finalizes disconnect by deleting Telegram webhook, clearing active credentials, and marking DISCONNECTED."""
        bot = await self.bot_repo.get_by_id(client_bot_id)
        if not bot:
            return False, "Bot not found"

        curr_status = enum_val(bot.status)
        if curr_status == ClientBotStatus.DISCONNECTED.value:
            return True, "Bot is already disconnected"

        # Attempt Telegram webhook removal
        raw_token = self.encryption_service.decrypt_token(bot.token_encrypted)
        if raw_token:
            tg_client = TelegramClient(token=raw_token, http_client=http_client)
            try:
                await tg_client.delete_webhook(drop_pending_updates=False)
            except Exception as exc:
                logger.warning(f"Could not delete webhook on Telegram for bot #{bot.id}: {exc}")

        # Clear active credentials and update state
        bot.status = ClientBotStatus.DISCONNECTED
        bot.disconnected_at = utc_now()
        bot.token_encrypted = None
        bot.webhook_secret_encrypted = None
        bot.status_reason = "CLIENT_DISCONNECTED"
        bot.last_status_changed_at = utc_now()
        bot.lifecycle_version = (bot.lifecycle_version or 0) + 1

        # Pause any pending broadcasts
        stmt_bc = (
            select(Broadcast)
            .where(
                Broadcast.client_bot_id == bot.id,
                Broadcast.status.in_([BroadcastStatus.RUNNING, BroadcastStatus.QUEUED]),
            )
        )
        res_bc = await self.session.execute(stmt_bc)
        for bc in res_bc.scalars().all():
            bc.status = BroadcastStatus.PAUSED

        # Record audit event
        await self.event_repo.record_event(
            client_bot_id=bot.id,
            event_type=BotEventType.BOT_DISCONNECTED,
            metadata_json={"disconnected_at": bot.disconnected_at.isoformat()},
        )

        await self.session.flush()
        logger.info(f"Bot #{bot.id} (@{bot.username}) disconnected and credentials cleared")
        return True, "Bot disconnected successfully"

    async def mark_invalid_token(
        self,
        client_bot_id: int,
        reason: str = "TOKEN_UNAUTHORIZED",
    ) -> bool:
        """Transitions bot to INVALID_TOKEN state upon confirmed Telegram authentication failure."""
        bot = await self.bot_repo.get_by_id(client_bot_id)
        if not bot:
            return False

        if enum_val(bot.status) == ClientBotStatus.INVALID_TOKEN.value:
            return True

        bot.status = ClientBotStatus.INVALID_TOKEN
        bot.status_reason = reason
        bot.last_status_changed_at = utc_now()
        bot.lifecycle_version = (bot.lifecycle_version or 0) + 1

        # Pause active broadcasts
        stmt_bc = (
            select(Broadcast)
            .where(
                Broadcast.client_bot_id == bot.id,
                Broadcast.status.in_([BroadcastStatus.RUNNING, BroadcastStatus.QUEUED]),
            )
        )
        res_bc = await self.session.execute(stmt_bc)
        for bc in res_bc.scalars().all():
            bc.status = BroadcastStatus.PAUSED

        await self.event_repo.record_event(
            client_bot_id=bot.id,
            event_type=BotEventType.BOT_TOKEN_INVALIDATED,
            metadata_json={"reason": reason, "timestamp": utc_now().isoformat()},
        )

        await self.session.flush()
        logger.warning(f"Bot #{bot.id} (@{bot.username}) marked INVALID_TOKEN (reason={reason})")
        return True

    async def mark_unavailable(
        self,
        client_bot_id: int,
        reason: str = "BOT_UNREACHABLE",
    ) -> bool:
        """Transitions bot to UNAVAILABLE operational state while preserving desired status for recovery."""
        bot = await self.bot_repo.get_by_id(client_bot_id)
        if not bot:
            return False

        if enum_val(bot.status) == ClientBotStatus.UNAVAILABLE.value:
            return True

        bot.desired_status = enum_val(bot.status)
        bot.status = ClientBotStatus.UNAVAILABLE
        bot.status_reason = reason
        bot.last_status_changed_at = utc_now()
        bot.lifecycle_version = (bot.lifecycle_version or 0) + 1

        await self.event_repo.record_event(
            client_bot_id=bot.id,
            event_type=BotEventType.BOT_UNAVAILABLE,
            metadata_json={"reason": reason, "desired_status": bot.desired_status},
        )

        await self.session.flush()
        logger.warning(f"Bot #{bot.id} marked UNAVAILABLE (reason={reason})")
        return True

    async def mark_revoked(
        self,
        client_bot_id: int,
        reason: str = "BOT_REVOKED",
    ) -> bool:
        """Transitions bot to REVOKED status."""
        bot = await self.bot_repo.get_by_id(client_bot_id)
        if not bot:
            return False

        bot.status = ClientBotStatus.REVOKED
        bot.status_reason = reason
        bot.last_status_changed_at = utc_now()
        bot.lifecycle_version = (bot.lifecycle_version or 0) + 1

        await self.event_repo.record_event(
            client_bot_id=bot.id,
            event_type=BotEventType.BOT_REVOKED,
            metadata_json={"reason": reason},
        )

        await self.session.flush()
        logger.warning(f"Bot #{bot.id} marked REVOKED (reason={reason})")
        return True

    async def resume_bot_work(self, client_bot_id: int) -> Dict[str, int]:
        """Resumes paused broadcast and catch-up jobs for an active bot."""
        # 1. Resume paused broadcasts -> QUEUED
        stmt_bc = (
            select(Broadcast)
            .where(
                Broadcast.client_bot_id == client_bot_id,
                Broadcast.status == BroadcastStatus.PAUSED,
            )
        )
        res_bc = await self.session.execute(stmt_bc)
        paused_bcs = res_bc.scalars().all()
        for bc in paused_bcs:
            bc.status = BroadcastStatus.QUEUED

        # 2. Resume paused catch-up sessions -> PENDING
        stmt_cu = (
            select(ViewerCatchup)
            .where(
                ViewerCatchup.client_bot_id == client_bot_id,
                ViewerCatchup.status == CatchupStatus.PAUSED,
            )
        )
        res_cu = await self.session.execute(stmt_cu)
        paused_cus = res_cu.scalars().all()
        for cu in paused_cus:
            cu.status = CatchupStatus.PENDING

        await self.session.flush()
        return {
            "resumed_broadcasts": len(paused_bcs),
            "resumed_catchups": len(paused_cus),
        }
