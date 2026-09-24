"""Client Bot Statistics Service with strict per-bot isolation and Redis caching."""

import json
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.redis.client import get_redis
from app.repositories.client_bot_stats import ClientBotStatsRepository

logger = get_logger(__name__)

STATS_CACHE_TTL = 30  # 30 seconds


class ClientBotStatsService:
    """Service providing isolated analytics for a specific Client Bot."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.stats_repo = ClientBotStatsRepository(session)

    async def _get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            redis = get_redis()
            data = await redis.get(key)
            if data:
                return json.loads(data)
        except Exception as exc:
            logger.debug(f"Redis stats cache get error: {exc}")
        return None

    async def _set_cached(self, key: str, data: Dict[str, Any], ttl: int = STATS_CACHE_TTL) -> None:
        try:
            redis = get_redis()
            await redis.set(key, json.dumps(data), ex=ttl)
        except Exception as exc:
            logger.debug(f"Redis stats cache set error: {exc}")

    async def get_stats_summary(self, client_bot_id: int, bypass_cache: bool = False) -> Dict[str, Any]:
        """Provides full /stats summary for a single bot."""
        cache_key = f"controlhub:stats:bot:{client_bot_id}:summary"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        users = await self.stats_repo.get_user_counts(client_bot_id)
        videos = await self.stats_repo.get_video_counts(client_bot_id)
        broadcasts = await self.stats_repo.get_broadcast_counts(client_bot_id)

        summary = {
            "client_bot_id": client_bot_id,
            "users": users,
            "videos": videos,
            "broadcasts": broadcasts,
        }

        await self._set_cached(cache_key, summary)
        return summary

    async def get_users_summary(self, client_bot_id: int, bypass_cache: bool = False) -> Dict[str, int]:
        """Provides /users detailed metrics for a single bot."""
        cache_key = f"controlhub:stats:bot:{client_bot_id}:users"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        users = await self.stats_repo.get_user_counts(client_bot_id)
        await self._set_cached(cache_key, users)
        return users

    async def get_videos_summary(self, client_bot_id: int, bypass_cache: bool = False) -> Dict[str, int]:
        """Provides /videos summary metrics for a single bot."""
        cache_key = f"controlhub:stats:bot:{client_bot_id}:videos"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        videos = await self.stats_repo.get_video_counts(client_bot_id)
        await self._set_cached(cache_key, videos)
        return videos

    async def get_processing_summary(self, client_bot_id: int, bypass_cache: bool = False) -> Dict[str, int]:
        """Provides /processing pipeline breakdown for a single bot."""
        cache_key = f"controlhub:stats:bot:{client_bot_id}:processing"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        processing = await self.stats_repo.get_processing_counts(client_bot_id)
        await self._set_cached(cache_key, processing)
        return processing

    async def get_broadcasts_summary(self, client_bot_id: int, bypass_cache: bool = False) -> Dict[str, int]:
        """Provides /broadcasts LIVE and Catch-Up metrics for a single bot."""
        cache_key = f"controlhub:stats:bot:{client_bot_id}:broadcasts"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        broadcasts = await self.stats_repo.get_broadcast_counts(client_bot_id)
        await self._set_cached(cache_key, broadcasts)
        return broadcasts
