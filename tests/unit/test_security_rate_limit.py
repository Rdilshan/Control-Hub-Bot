"""Unit tests for SecurityRateLimiter."""

import pytest
from unittest.mock import AsyncMock
from app.security.rate_limit import SecurityRateLimiter


@pytest.mark.asyncio
async def test_security_rate_limiter_allows_under_threshold():
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 1
    mock_redis.expire.return_value = True

    limiter = SecurityRateLimiter(redis_client=mock_redis)

    allowed = await limiter.check_viewer_rate_limit(client_bot_id=1, telegram_user_id=123, max_requests=10)
    assert allowed is True
    mock_redis.incr.assert_called_once()
    mock_redis.expire.assert_called_once()


@pytest.mark.asyncio
async def test_security_rate_limiter_blocks_above_threshold():
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 11  # Exceeded max_requests=10

    limiter = SecurityRateLimiter(redis_client=mock_redis)

    allowed = await limiter.check_viewer_rate_limit(client_bot_id=1, telegram_user_id=123, max_requests=10)
    assert allowed is False


@pytest.mark.asyncio
async def test_connect_attempt_tracking_and_blocking():
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 6
    mock_redis.get.return_value = "6"

    limiter = SecurityRateLimiter(redis_client=mock_redis)

    # 6 attempts > 5 max attempts -> should report blocked
    is_exceeded = await limiter.record_invalid_connect_attempt(telegram_user_id=456, max_attempts=5)
    assert is_exceeded is True

    is_blocked = await limiter.is_connect_attempt_blocked(telegram_user_id=456, max_attempts=5)
    assert is_blocked is True
