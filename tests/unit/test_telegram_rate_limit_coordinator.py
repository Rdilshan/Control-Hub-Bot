"""Unit tests for TelegramRateLimitCoordinator."""

import time
import pytest
from app.services.telegram_rate_limit_coordinator import TelegramRateLimitCoordinator


@pytest.mark.asyncio
async def test_telegram_rate_limit_coordinator_in_memory():
    coordinator = TelegramRateLimitCoordinator(redis_client=None)

    # Initially not rate limited
    assert await coordinator.is_rate_limited(client_bot_id=1) is False
    assert await coordinator.get_wait_seconds(client_bot_id=1) == 0.0

    # Set rate limit for 5 seconds
    await coordinator.set_rate_limit(client_bot_id=1, retry_after_seconds=5)

    assert await coordinator.is_rate_limited(client_bot_id=1) is True
    wait_s = await coordinator.get_wait_seconds(client_bot_id=1)
    assert 3.0 <= wait_s <= 6.0

    # Different bot is unaffected
    assert await coordinator.is_rate_limited(client_bot_id=2) is False

    # Clear rate limit
    await coordinator.clear_rate_limit(client_bot_id=1)
    assert await coordinator.is_rate_limited(client_bot_id=1) is False
