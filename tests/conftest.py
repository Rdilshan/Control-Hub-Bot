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


@pytest_asyncio.fixture
async def app_client():
    """Provides an AsyncClient bound to the FastAPI application."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
