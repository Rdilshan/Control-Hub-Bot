"""Platform Statistics Service providing platform-wide statistics for Platform Owner."""

import json
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.redis.client import get_redis
from app.repositories.platform_stats import PlatformStatsRepository

logger = get_logger(__name__)

PLATFORM_STATS_CACHE_TTL = 30  # 30 seconds


class PlatformStatsService:
    """Service providing aggregate analytics for the entire platform."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.stats_repo = PlatformStatsRepository(session)

    async def _get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            redis = get_redis()
            data = await redis.get(key)
            if data:
                return json.loads(data)
        except Exception as exc:
            logger.debug(f"Redis platform stats cache get error: {exc}")
        return None

    async def _set_cached(self, key: str, data: Dict[str, Any], ttl: int = PLATFORM_STATS_CACHE_TTL) -> None:
        try:
            redis = get_redis()
            await redis.set(key, json.dumps(data), ex=ttl)
        except Exception as exc:
            logger.debug(f"Redis platform stats cache set error: {exc}")

    async def get_system_stats(self, bypass_cache: bool = False) -> Dict[str, Any]:
        """Provides full /systemstats platform overview."""
        cache_key = "controlhub:stats:platform:systemstats"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        stats = await self.stats_repo.get_system_stats()
        await self._set_cached(cache_key, stats)
        return stats

    async def get_client_counts(self, bypass_cache: bool = False) -> Dict[str, int]:
        cache_key = "controlhub:stats:platform:clients"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        clients = await self.stats_repo.get_client_counts()
        await self._set_cached(cache_key, clients)
        return clients

    async def get_bot_counts(self, bypass_cache: bool = False) -> Dict[str, int]:
        cache_key = "controlhub:stats:platform:bots"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        bots = await self.stats_repo.get_bot_counts()
        await self._set_cached(cache_key, bots)
        return bots

    async def get_viewer_counts(self, bypass_cache: bool = False) -> Dict[str, int]:
        cache_key = "controlhub:stats:platform:viewers"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        viewers = await self.stats_repo.get_viewer_counts()
        await self._set_cached(cache_key, viewers)
        return viewers

    async def get_video_counts(self, bypass_cache: bool = False) -> Dict[str, int]:
        cache_key = "controlhub:stats:platform:videos"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        videos = await self.stats_repo.get_video_counts()
        await self._set_cached(cache_key, videos)
        return videos

    async def get_job_counts(self, bypass_cache: bool = False) -> Dict[str, int]:
        cache_key = "controlhub:stats:platform:jobs"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        jobs = await self.stats_repo.get_job_counts()
        await self._set_cached(cache_key, jobs)
        return jobs

    async def get_broadcast_counts(self, bypass_cache: bool = False) -> Dict[str, int]:
        cache_key = "controlhub:stats:platform:broadcasts"
        if not bypass_cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        broadcasts = await self.stats_repo.get_broadcast_counts()
        await self._set_cached(cache_key, broadcasts)
        return broadcasts
