"""Telegram Rate Limit Coordinator across multiple workers and bots."""

import time
from datetime import datetime, timezone
from typing import Dict, Optional
import redis.asyncio as aioredis
from app.core.utils import utc_now


class TelegramRateLimitCoordinator:
    """Coordinates per-bot Telegram rate limits across LIVE broadcasts, Catch-Up, and deliveries."""

    _in_memory_limits: Dict[int, float] = {}

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self.redis = redis_client

    def _redis_key(self, client_bot_id: int) -> str:
        return f"controlhub:telegram-rate:{client_bot_id}"

    async def set_rate_limit(self, client_bot_id: int, retry_after_seconds: int) -> None:
        """Records a 429 rate limit backoff for the specified bot."""
        blocked_until_ts = time.time() + max(1, retry_after_seconds)
        self._in_memory_limits[client_bot_id] = blocked_until_ts

        if self.redis:
            try:
                await self.redis.set(
                    self._redis_key(client_bot_id),
                    str(blocked_until_ts),
                    ex=max(1, retry_after_seconds) + 5,
                )
            except Exception:
                pass  # In-memory fallback handles local process

    async def is_rate_limited(self, client_bot_id: int) -> bool:
        """Checks whether the bot is currently in a 429 rate limit cooldown."""
        return (await self.get_wait_seconds(client_bot_id)) > 0.0

    async def get_wait_seconds(self, client_bot_id: int) -> float:
        """Returns remaining cooldown in seconds, or 0.0 if not rate limited."""
        now_ts = time.time()

        if self.redis:
            try:
                val = await self.redis.get(self._redis_key(client_bot_id))
                if val:
                    blocked_until_ts = float(val)
                    remaining = blocked_until_ts - now_ts
                    if remaining > 0:
                        return remaining
            except Exception:
                pass

        mem_val = self._in_memory_limits.get(client_bot_id, 0.0)
        remaining = mem_val - now_ts
        return max(0.0, remaining)

    async def clear_rate_limit(self, client_bot_id: int) -> None:
        """Clears any active rate limit for the bot."""
        self._in_memory_limits.pop(client_bot_id, None)
        if self.redis:
            try:
                await self.redis.delete(self._redis_key(client_bot_id))
            except Exception:
                pass
