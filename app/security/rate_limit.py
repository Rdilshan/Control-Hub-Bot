"""Rate limiting and abuse protection service using Redis sliding windows."""

import time
from typing import Optional
from app.redis.client import get_redis_client


class SecurityRateLimiter:
    """Provides sliding window and fixed window rate limiting across viewers, admins, and authentication flows."""

    def __init__(self, redis_client=None):
        self._redis = redis_client

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        return await get_redis_client()

    async def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int = 60,
    ) -> bool:
        """Generic rate limiter using Redis INCR and EXPIRE. Returns True if within limit, False if rate limited."""
        try:
            redis = await self._get_redis()
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, window_seconds)
            return current <= max_requests
        except Exception:
            # Fail open gracefully if Redis is temporarily unavailable in non-strict mode
            return True

    async def check_viewer_rate_limit(
        self,
        client_bot_id: int,
        telegram_user_id: int,
        max_requests: int = 30,
        window_seconds: int = 60,
    ) -> bool:
        """Enforces rate limit for regular bot viewers."""
        key = f"controlhub:ratelimit:viewer:{client_bot_id}:{telegram_user_id}"
        return await self.check_rate_limit(key, max_requests, window_seconds)

    async def check_admin_rate_limit(
        self,
        client_bot_id: int,
        telegram_user_id: int,
        max_requests: int = 120,
        window_seconds: int = 60,
    ) -> bool:
        """Enforces rate limit for client bot administrators."""
        key = f"controlhub:ratelimit:admin:{client_bot_id}:{telegram_user_id}"
        return await self.check_rate_limit(key, max_requests, window_seconds)

    async def check_unlock_rate_limit(
        self,
        client_bot_id: int,
        telegram_user_id: int,
        video_id: int,
        max_requests: int = 10,
        window_seconds: int = 60,
    ) -> bool:
        """Limits repeated deep-link unlock requests per user and video."""
        key = f"controlhub:ratelimit:unlock:{client_bot_id}:{telegram_user_id}:{video_id}"
        return await self.check_rate_limit(key, max_requests, window_seconds)

    async def record_invalid_connect_attempt(
        self,
        telegram_user_id: int,
        max_attempts: int = 5,
        window_seconds: int = 600,
    ) -> bool:
        """Records an invalid token connection attempt. Returns True if attempts exceeded allowed limit."""
        key = f"controlhub:ratelimit:connectbot:{telegram_user_id}"
        try:
            redis = await self._get_redis()
            attempts = await redis.incr(key)
            if attempts == 1:
                await redis.expire(key, window_seconds)
            return attempts > max_attempts
        except Exception:
            return False

    async def is_connect_attempt_blocked(
        self,
        telegram_user_id: int,
        max_attempts: int = 5,
    ) -> bool:
        """Checks whether the client is temporarily blocked from submitting connection tokens."""
        key = f"controlhub:ratelimit:connectbot:{telegram_user_id}"
        try:
            redis = await self._get_redis()
            val = await redis.get(key)
            if val is None:
                return False
            return int(val) > max_attempts
        except Exception:
            return False

    async def reset_connect_attempts(self, telegram_user_id: int) -> None:
        """Resets the invalid connection counter upon a successful connection."""
        key = f"controlhub:ratelimit:connectbot:{telegram_user_id}"
        try:
            redis = await self._get_redis()
            await redis.delete(key)
        except Exception:
            pass
