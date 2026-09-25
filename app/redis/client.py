"""Async Redis client wrapper and health checks."""

from typing import Optional, Any
import redis.asyncio as aioredis
from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

_redis_client: Optional[aioredis.Redis] = None


class RedisManager:
    """Async Redis wrapper for key-value, locks, sessions, and queues."""

    def __init__(self, client: aioredis.Redis):
        self._client = client

    @property
    def client(self) -> aioredis.Redis:
        return self._client

    async def ping(self) -> bool:
        """Sends PING to Redis server, returns True on PONG."""
        try:
            return bool(await self._client.ping())
        except Exception as exc:
            logger.warning(f"Redis ping failed: {exc}")
            return False

    async def get(self, key: str) -> Optional[str]:
        """Gets value for key as decoded string."""
        return await self._client.get(key)

    async def set(
        self,
        key: str,
        value: Any,
        expire_seconds: Optional[int] = None,
    ) -> bool:
        """Sets key to value with optional TTL expiration."""
        return bool(await self._client.set(key, value, ex=expire_seconds))

    async def delete(self, *keys: str) -> int:
        """Deletes one or more keys from Redis."""
        if not keys:
            return 0
        return int(await self._client.delete(*keys))

    async def expire(self, key: str, seconds: int) -> bool:
        """Sets expiration on a key."""
        return bool(await self._client.expire(key, seconds))

    async def exists(self, *keys: str) -> int:
        """Checks if key(s) exist."""
        if not keys:
            return 0
        return int(await self._client.exists(*keys))


def get_redis() -> aioredis.Redis:
    """Gets the global Redis client instance."""
    global _redis_client
    if _redis_client is None:
        init_redis()
    return _redis_client


get_redis_client = get_redis


def init_redis(redis_url: Optional[str] = None) -> aioredis.Redis:
    """Initializes the async Redis client."""
    global _redis_client
    settings = get_settings()
    url = redis_url or settings.REDIS_URL
    _redis_client = aioredis.from_url(
        url,
        decode_responses=True,
        max_connections=20,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    logger.info("Redis client initialized")
    return _redis_client


async def close_redis() -> None:
    """Closes Redis client connections upon shutdown."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis client connection closed")


async def check_redis_health() -> bool:
    """Checks whether Redis is accessible."""
    try:
        client = get_redis()
        return bool(await client.ping())
    except Exception as exc:
        logger.warning(f"Redis health check failed: {exc}")
        return False
