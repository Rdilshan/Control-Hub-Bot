"""Pytest fixtures and configuration."""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.config import Settings, get_settings
from app.core.enums import Environment
from app.main import create_app


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    """Sets environment variables for testing."""
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("INTERNAL_API_SECRET", "test_internal_secret")
    monkeypatch.setenv("CONTROL_HUB_BOT_TOKEN", "123456789:TEST_BOT_TOKEN_ABC_DEF")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


from unittest.mock import AsyncMock


class FakeRedis:
    """Fast in-memory Redis mock for unit/integration tests."""

    def __init__(self):
        self._store = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value, ex=None, **kwargs):
        self._store[key] = str(value) if not isinstance(value, bytes) else value.decode("utf-8")
        return True

    async def setex(self, key: str, time, value):
        self._store[key] = str(value) if not isinstance(value, bytes) else value.decode("utf-8")
        return True

    async def delete(self, *keys: str):
        count = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                count += 1
        return count

    async def ping(self):
        return True

    async def expire(self, key: str, seconds: int):
        return True

    async def exists(self, *keys: str):
        return sum(1 for k in keys if k in self._store)


@pytest.fixture(autouse=True)
def mock_redis_globally(monkeypatch):
    """Mocks Redis client with in-memory store so tests run instantly without socket delays."""
    fake = FakeRedis()
    monkeypatch.setattr("app.redis.client.get_redis", lambda: fake)
    yield fake


@pytest_asyncio.fixture
async def app_client():
    """Provides an AsyncClient bound to the FastAPI application."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def db_session():
    """Provides an isolated in-memory SQLite AsyncSession for tests."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.db.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()
