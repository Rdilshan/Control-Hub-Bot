"""Per-bot and global async rate limiter for Telegram broadcast dispatching."""

import asyncio
import time
from typing import Dict, Optional
from app.config import get_settings
from app.logging_config import logger


class TelegramBroadcastRateLimiter:
    """Controls outgoing broadcast dispatch rates per bot and handles Telegram 429 pause windows."""

    def __init__(
        self,
        default_rate_per_second: Optional[float] = None,
        global_rate_per_second: Optional[float] = None,
    ):
        settings = get_settings()
        self.rate_per_second = (
            default_rate_per_second
            if default_rate_per_second is not None
            else getattr(settings, "TELEGRAM_BROADCAST_RATE_PER_SECOND", 25.0)
        )
        self.min_interval = 1.0 / self.rate_per_second if self.rate_per_second > 0 else 0.0

        self.global_min_interval = (
            (1.0 / global_rate_per_second)
            if global_rate_per_second and global_rate_per_second > 0
            else 0.0
        )

        self._bot_last_send: Dict[int, float] = {}
        self._bot_pause_until: Dict[int, float] = {}
        self._global_last_send: float = 0.0
        self._locks: Dict[int, asyncio.Lock] = {}
        self._master_lock = asyncio.Lock()

    def _get_lock(self, client_bot_id: int) -> asyncio.Lock:
        if client_bot_id not in self._locks:
            self._locks[client_bot_id] = asyncio.Lock()
        return self._locks[client_bot_id]

    def pause_bot(self, client_bot_id: int, retry_after: float) -> None:
        """Pauses all outgoing sends for a specific bot following a Telegram 429 response."""
        resume_at = time.monotonic() + max(0.0, retry_after)
        self._bot_pause_until[client_bot_id] = resume_at
        logger.warning(
            "Bot id=%d rate limited by Telegram. Paused broadcast sends for %.1f seconds",
            client_bot_id,
            retry_after,
        )

    def is_bot_paused(self, client_bot_id: int) -> bool:
        """Returns True if the bot is currently in a 429 pause window."""
        pause_until = self._bot_pause_until.get(client_bot_id, 0.0)
        return time.monotonic() < pause_until

    async def acquire(self, client_bot_id: int) -> None:
        """Waits asynchronously until it is safe to send a message for the specified client bot."""
        lock = self._get_lock(client_bot_id)
        async with lock:
            # 1. Respect 429 pause window
            now = time.monotonic()
            pause_until = self._bot_pause_until.get(client_bot_id, 0.0)
            if now < pause_until:
                wait_time = pause_until - now
                logger.debug(
                    "Bot id=%d waiting %.2fs for Telegram 429 pause window to clear",
                    client_bot_id,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
                now = time.monotonic()

            # 2. Respect per-bot interval
            if self.min_interval > 0:
                last_send = self._bot_last_send.get(client_bot_id, 0.0)
                elapsed = now - last_send
                if elapsed < self.min_interval:
                    sleep_needed = self.min_interval - elapsed
                    await asyncio.sleep(sleep_needed)

            # 3. Respect global rate limiter if configured
            if self.global_min_interval > 0:
                async with self._master_lock:
                    now = time.monotonic()
                    global_elapsed = now - self._global_last_send
                    if global_elapsed < self.global_min_interval:
                        await asyncio.sleep(self.global_min_interval - global_elapsed)
                    self._global_last_send = time.monotonic()

            # Record send time
            self._bot_last_send[client_bot_id] = time.monotonic()


# Global rate limiter instance
telegram_rate_limiter = TelegramBroadcastRateLimiter()
