"""Integration/Unit tests for DB session and Redis client mechanisms."""

import pytest
from app.db.session import check_db_health
from app.redis.client import RedisManager


@pytest.mark.asyncio
async def test_redis_manager_operations(mocker):
    """Tests RedisManager operations with mock redis client."""
    mock_redis = mocker.AsyncMock()
    mock_redis.ping.return_value = True
    mock_redis.get.return_value = "cached_val"
    mock_redis.set.return_value = True
    mock_redis.delete.return_value = 1
    mock_redis.expire.return_value = True
    mock_redis.exists.return_value = 1

    manager = RedisManager(mock_redis)

    assert await manager.ping() is True
    assert await manager.get("controlhub:session:1") == "cached_val"
    assert await manager.set("controlhub:session:1", "val", expire_seconds=60) is True
    assert await manager.delete("controlhub:session:1") == 1
    assert await manager.expire("controlhub:session:1", 60) is True
    assert await manager.exists("controlhub:session:1") == 1


@pytest.mark.asyncio
async def test_db_health_check_failure_recovery(mocker):
    """Verifies check_db_health returns False gracefully on connection error."""
    mocker.patch("app.db.session.async_session_factory", side_effect=Exception("DB unreachable"))
    result = await check_db_health()
    assert result is False
