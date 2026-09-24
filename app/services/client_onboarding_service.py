"""Client Onboarding Service managing client lifecycle, onboarding states, and bot listings."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ClientBotStatus, ClientStatus, enum_val
from app.core.utils import utc_now
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.logging_config import get_logger
from app.redis.client import get_redis
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.repositories.video import VideoRepository
from app.repositories.viewer import ViewerRepository

logger = get_logger(__name__)

ONBOARDING_STATE_PREFIX = "controlhub:onboarding:"
ONBOARDING_STATE_TTL = 1800  # 30 minutes

# Resilient in-memory fallback store for development & tests when Redis is not running
_in_memory_onboarding_store: Dict[int, str] = {}


class ClientOnboardingService:
    """Manages Client Onboarding, profile synchronization, account views, and state management."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.client_repo = ClientRepository(session)
        self.bot_repo = ClientBotRepository(session)
        self.viewer_repo = ViewerRepository(session)
        self.video_repo = VideoRepository(session)

    # --- 1. Client Identity & Profile Synchronization ---

    async def resolve_or_create_client(
        self,
        telegram_user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> Tuple[Client, bool]:
        """Gets existing client or creates new client record, synchronizing profile data."""
        client, is_new = await self.client_repo.get_or_create(
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        if is_new:
            logger.info(f"New client registered: #{client.id} (Telegram ID: {telegram_user_id}, @{username})")
        return client, is_new

    async def get_client_by_telegram_id(self, telegram_user_id: int) -> Optional[Client]:
        return await self.client_repo.get_by_telegram_user_id(telegram_user_id)

    # --- 2. Client Home & Account Summaries ---

    async def get_client_home_summary(self, client_id: int) -> Dict[str, Any]:
        client = await self.client_repo.get_by_id(client_id)
        if not client:
            return {"status": "UNKNOWN", "total_bots": 0, "active_bots": 0}

        bots = await self.bot_repo.list_by_client(client_id)
        active_bots = [b for b in bots if enum_val(b.status) == ClientBotStatus.ACTIVE.value]
        paused_bots = [b for b in bots if enum_val(b.status) == ClientBotStatus.PAUSED.value]

        return {
            "client": client,
            "status": enum_val(client.status),
            "total_bots": len(bots),
            "active_bots": len(active_bots),
            "paused_bots": len(paused_bots),
            "bots": bots,
        }

    async def get_client_account_summary(self, client_id: int) -> Dict[str, Any]:
        client = await self.client_repo.get_by_id(client_id)
        if not client:
            return {}

        bots = await self.bot_repo.list_by_client(client_id)
        return {
            "client_id": client.id,
            "telegram_user_id": client.telegram_user_id,
            "username": client.username,
            "first_name": client.first_name,
            "status": enum_val(client.status),
            "total_bots": len(bots),
            "created_at": client.created_at,
        }

    # --- 3. Client Bots (Strict Multi-Tenant Isolation) ---

    async def list_client_bots(self, client_id: int) -> List[ClientBot]:
        return await self.bot_repo.list_by_client(client_id)

    async def get_bot_for_client(self, bot_id: int, client_id: int) -> Optional[Dict[str, Any]]:
        bot = await self.bot_repo.get_by_id_and_client(bot_id=bot_id, client_id=client_id)
        if not bot:
            return None

        users_count = await self.viewer_repo.count_by_bot(bot.id)
        videos_count = await self.video_repo.count_by_bot(bot.id)

        return {
            "bot": bot,
            "users_count": users_count,
            "videos_count": videos_count,
        }

    # --- 4. Redis-Backed Onboarding State Management (with In-Memory Fallback) ---

    async def get_onboarding_state(self, telegram_user_id: int) -> Optional[str]:
        try:
            redis = get_redis()
            val = await redis.get(f"{ONBOARDING_STATE_PREFIX}{telegram_user_id}")
            if val:
                return val
        except Exception:
            pass
        return _in_memory_onboarding_store.get(telegram_user_id)

    async def set_onboarding_state(
        self,
        telegram_user_id: int,
        state: str,
        ttl_seconds: int = ONBOARDING_STATE_TTL,
    ) -> bool:
        _in_memory_onboarding_store[telegram_user_id] = state
        try:
            redis = get_redis()
            return bool(
                await redis.set(f"{ONBOARDING_STATE_PREFIX}{telegram_user_id}", state, ex=ttl_seconds)
            )
        except Exception:
            return True

    async def clear_onboarding_state(self, telegram_user_id: int) -> bool:
        _in_memory_onboarding_store.pop(telegram_user_id, None)
        try:
            redis = get_redis()
            await redis.delete(f"{ONBOARDING_STATE_PREFIX}{telegram_user_id}")
            return True
        except Exception:
            return True
