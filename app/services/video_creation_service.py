"""Video Creation Service managing intake, metadata extraction, and processing job queuing."""

import asyncio
from typing import Any, Dict, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    BotEventType,
    ClientBotStatus,
    JobStatus,
    JobType,
    ProcessingStatus,
    VideoStatus,
    enum_val,
)
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.bot_event import BotEvent
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.logging_config import get_logger
from app.redis.client import get_redis
from app.repositories.client_bot_admin import ClientBotAdminRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.sponsor import SponsorRepository
from app.repositories.video import VideoRepository
from app.services.telegram_video_metadata_extractor import TelegramVideoMetadataExtractor
from app.telegram.client import TelegramClient
from app.telegram.client_bot import messages

logger = get_logger(__name__)

CREATE_VIDEO_STATE_PREFIX = "controlhub:clientbot:state:"
CREATE_VIDEO_STATE_TTL = 1800  # 30 minutes
WAITING_FOR_VIDEO = "WAITING_FOR_VIDEO"
ACCEPTING_VIDEO = "ACCEPTING_VIDEO"

_in_memory_state_store: Dict[str, str] = {}
_state_lock = asyncio.Lock()


class VideoCreationService:
    """Manages the video creation session, media verification, database persistence, and job initialization."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.video_repo = VideoRepository(session)
        self.sponsor_repo = SponsorRepository(session)
        self.job_repo = BackgroundJobRepository(session)
        self.admin_repo = ClientBotAdminRepository(session)

    # --- Session State Management ---

    async def get_creation_state(self, client_bot_id: int, telegram_user_id: int) -> Optional[str]:
        key = f"{CREATE_VIDEO_STATE_PREFIX}{client_bot_id}:{telegram_user_id}"
        try:
            redis = get_redis()
            return await redis.get(key)
        except Exception:
            async with _state_lock:
                return _in_memory_state_store.get(key)

    async def set_creation_state(self, client_bot_id: int, telegram_user_id: int, state: str) -> None:
        key = f"{CREATE_VIDEO_STATE_PREFIX}{client_bot_id}:{telegram_user_id}"
        try:
            redis = get_redis()
            await redis.set(key, state, ex=CREATE_VIDEO_STATE_TTL)
        except Exception:
            async with _state_lock:
                _in_memory_state_store[key] = state

    async def claim_creation_state(self, client_bot_id: int, telegram_user_id: int) -> bool:
        """Atomically transitions state from WAITING_FOR_VIDEO to ACCEPTING_VIDEO."""
        key = f"{CREATE_VIDEO_STATE_PREFIX}{client_bot_id}:{telegram_user_id}"
        try:
            redis = get_redis()
            # Redis Lua script for atomic state claim
            script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                redis.call('set', KEYS[1], ARGV[2], 'EX', ARGV[3])
                return 1
            else
                return 0
            end
            """
            result = await redis.eval(script, 1, key, WAITING_FOR_VIDEO, ACCEPTING_VIDEO, CREATE_VIDEO_STATE_TTL)
            return bool(result)
        except Exception:
            async with _state_lock:
                if _in_memory_state_store.get(key) == WAITING_FOR_VIDEO:
                    _in_memory_state_store[key] = ACCEPTING_VIDEO
                    return True
                return False

    async def clear_creation_state(self, client_bot_id: int, telegram_user_id: int) -> None:
        key = f"{CREATE_VIDEO_STATE_PREFIX}{client_bot_id}:{telegram_user_id}"
        try:
            redis = get_redis()
            await redis.delete(key)
        except Exception:
            async with _state_lock:
                _in_memory_state_store.pop(key, None)

    # --- Workflow Handlers ---

    async def start_create_video_session(
        self,
        client_bot: ClientBot,
        telegram_user_id: int,
        chat_id: int,
        telegram_client: TelegramClient,
    ) -> Dict[str, Any]:
        """Initiates a /createvideo session after checking prerequisites."""
        # 1. Guard: Client bot status
        if enum_val(client_bot.status) != ClientBotStatus.ACTIVE.value:
            await telegram_client.send_message(
                chat_id=chat_id,
                text=messages.bot_inactive_message(),
            )
            return {"ok": False, "error": "bot_not_active"}

        # 2. Guard: Sponsor configuration check
        sponsor_config = await self.sponsor_repo.get_by_bot_id(client_bot.id)
        if not sponsor_config or not sponsor_config.is_enabled:
            await telegram_client.send_message(
                chat_id=chat_id,
                text=messages.sponsor_required_message(),
            )
            return {"ok": False, "error": "sponsor_required"}

        # 3. Set WAITING_FOR_VIDEO state
        await self.set_creation_state(client_bot.id, telegram_user_id, WAITING_FOR_VIDEO)

        # 4. Send prompt to admin
        await telegram_client.send_message(
            chat_id=chat_id,
            text=messages.create_video_prompt_message(),
        )
        return {"ok": True, "action": "create_video_prompt_sent"}

    async def cancel_create_video_session(
        self,
        client_bot_id: int,
        telegram_user_id: int,
        chat_id: int,
        telegram_client: TelegramClient,
    ) -> Dict[str, Any]:
        """Cancels an active /createvideo session."""
        await self.clear_creation_state(client_bot_id, telegram_user_id)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=messages.create_video_cancelled_message(),
        )
        return {"ok": True, "action": "create_video_cancelled"}

    async def process_video_intake(
        self,
        client_bot: ClientBot,
        telegram_user_id: int,
        chat_id: int,
        admin_id: Optional[int],
        actor_data: Dict[str, Any],
        telegram_client: TelegramClient,
    ) -> Dict[str, Any]:
        """Processes video input or prompts correction while in WAITING_FOR_VIDEO."""
        text = actor_data.get("text") or ""
        if text.lower() in ("/cancel", "cancel"):
            return await self.cancel_create_video_session(
                client_bot_id=client_bot.id,
                telegram_user_id=telegram_user_id,
                chat_id=chat_id,
                telegram_client=telegram_client,
            )

        video = actor_data.get("video")
        document = actor_data.get("document")

        # 1. Non-video file (Document) warning: keep WAITING_FOR_VIDEO active
        if document and not video:
            await telegram_client.send_message(
                chat_id=chat_id,
                text=messages.create_video_document_warning_message(),
            )
            return {"ok": True, "action": "document_warning_sent"}

        # 2. General non-video input warning: keep WAITING_FOR_VIDEO active
        if not video:
            await telegram_client.send_message(
                chat_id=chat_id,
                text=messages.create_video_non_video_warning_message(),
            )
            return {"ok": True, "action": "non_video_warning_sent"}

        # 3. Atomic State Claim (WAITING_FOR_VIDEO -> ACCEPTING_VIDEO)
        claimed = await self.claim_creation_state(client_bot.id, telegram_user_id)
        if not claimed:
            curr_state = await self.get_creation_state(client_bot.id, telegram_user_id)
            if curr_state is None:
                await telegram_client.send_message(
                    chat_id=chat_id,
                    text=messages.create_video_expired_message(),
                )
                return {"ok": False, "error": "session_expired"}
            return {"ok": False, "error": "session_already_claimed"}

        # 4. Re-check Admin Authorization
        if admin_id is None:
            admin_record = await self.admin_repo.get_by_telegram_user_id(client_bot.id, telegram_user_id)
            if admin_record:
                if not admin_record.is_active:
                    await self.clear_creation_state(client_bot.id, telegram_user_id)
                    await telegram_client.send_message(
                        chat_id=chat_id,
                        text=messages.admin_only_command_message(),
                    )
                    return {"ok": False, "error": "admin_unauthorized"}
                admin_id = admin_record.id
            else:
                from app.db.models.client import Client
                from app.core.enums import ClientStatus
                client_owner = await self.session.get(Client, client_bot.client_id)
                if not client_owner or client_owner.telegram_user_id != telegram_user_id or enum_val(client_owner.status) != ClientStatus.ACTIVE.value:
                    await self.clear_creation_state(client_bot.id, telegram_user_id)
                    await telegram_client.send_message(
                        chat_id=chat_id,
                        text=messages.admin_only_command_message(),
                    )
                    return {"ok": False, "error": "admin_unauthorized"}

        # 5. Re-check Client Bot Status
        bot_status_str = enum_val(client_bot.status)
        if bot_status_str == ClientBotStatus.PAUSED.value:
            await self.clear_creation_state(client_bot.id, telegram_user_id)
            await telegram_client.send_message(
                chat_id=chat_id,
                text=messages.bot_paused_admin_message(client_bot.username),
            )
            return {"ok": False, "error": "bot_paused"}
        elif bot_status_str != ClientBotStatus.ACTIVE.value:
            await self.clear_creation_state(client_bot.id, telegram_user_id)
            await telegram_client.send_message(
                chat_id=chat_id,
                text=messages.bot_inactive_message(),
            )
            return {"ok": False, "error": "bot_not_active"}

        # 6. Re-check Sponsor Configuration
        sponsor_config = await self.sponsor_repo.get_by_bot_id(client_bot.id)
        if not sponsor_config or not sponsor_config.is_enabled:
            await self.clear_creation_state(client_bot.id, telegram_user_id)
            await telegram_client.send_message(
                chat_id=chat_id,
                text=messages.sponsor_required_message(),
            )
            return {"ok": False, "error": "sponsor_required"}

        # 7. Extract Video Metadata (no full video download)
        metadata = TelegramVideoMetadataExtractor.extract(actor_data, chat_id=chat_id)
        if not metadata:
            await self.set_creation_state(client_bot.id, telegram_user_id, WAITING_FOR_VIDEO)
            await telegram_client.send_message(
                chat_id=chat_id,
                text=messages.create_video_non_video_warning_message(),
            )
            return {"ok": False, "error": "invalid_video_data"}

        # 8. Idempotency check for duplicate message deliveries
        if metadata.message_id:
            existing = await self.video_repo.get_by_telegram_message(
                client_bot_id=client_bot.id,
                source_chat_id=metadata.chat_id,
                telegram_message_id=metadata.message_id,
            )
            if existing:
                logger.info(f"Duplicate video message #{metadata.message_id} ignored for bot #{client_bot.id}")
                await self.clear_creation_state(client_bot.id, telegram_user_id)
                await telegram_client.send_message(
                    chat_id=chat_id,
                    text=messages.create_video_success_message(),
                )
                return {"ok": True, "action": "duplicate_video_skipped", "video_id": existing.id}

        # 9. Database Transaction: Video + Processing + Job + Event
        try:
            new_video = await self.video_repo.create_video(
                client_bot_id=client_bot.id,
                created_by_admin_id=admin_id,
                telegram_file_id=metadata.file_id,
                telegram_file_unique_id=metadata.file_unique_id,
                telegram_message_id=metadata.message_id,
                source_chat_id=metadata.chat_id,
                source_thumbnail_file_id=metadata.source_thumbnail_file_id,
                source_thumbnail_file_unique_id=metadata.source_thumbnail_file_unique_id,
                file_name=metadata.file_name,
                mime_type=metadata.mime_type,
                file_size=metadata.file_size,
                duration_seconds=metadata.duration_seconds,
                width=metadata.width,
                height=metadata.height,
                caption=metadata.caption,
            )

            # Ensure active background job is created
            active_job = await self.job_repo.get_active_for_video(new_video.id)
            if not active_job:
                await self.job_repo.create_video_processing_job(
                    video_id=new_video.id,
                    client_bot_id=client_bot.id,
                    client_id=client_bot.client_id,
                    thumbnail_file_id=metadata.source_thumbnail_file_id,
                )

            await self.session.commit()
        except Exception as e:
            logger.error(f"Failed to create video for bot #{client_bot.id}: {e}", exc_info=True)
            await self.session.rollback()
            await self.set_creation_state(client_bot.id, telegram_user_id, WAITING_FOR_VIDEO)
            await telegram_client.send_message(
                chat_id=chat_id,
                text=messages.create_video_error_message(),
            )
            return {"ok": False, "error": "db_transaction_failed"}

        # 10. Close session immediately (one video per session rule)
        await self.clear_creation_state(client_bot.id, telegram_user_id)

        # 11. Send immediate success confirmation
        await telegram_client.send_message(
            chat_id=chat_id,
            text=messages.create_video_success_message(),
        )

        logger.info(f"Video #{new_video.id} (public_id: {new_video.public_id}) created successfully for bot #{client_bot.id}")
        return {
            "ok": True,
            "action": "video_created",
            "video_id": new_video.id,
            "public_id": new_video.public_id,
        }
