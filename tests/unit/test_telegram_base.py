"""Unit tests for Telegram client and exception mapping."""

import pytest
import httpx
from app.telegram.client import TelegramClient, validate_bot_token
from app.telegram.errors import (
    TelegramForbiddenError,
    TelegramInvalidTokenError,
    TelegramNetworkError,
    TelegramRateLimitError,
)


@pytest.mark.asyncio
async def test_telegram_get_me_success(monkeypatch):
    """Verifies getMe properly parses TelegramBotInfo."""
    async def mock_handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "id": 987654321,
                    "is_bot": True,
                    "first_name": "Test Bot",
                    "username": "test_hub_bot",
                    "can_join_groups": True,
                },
            },
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        bot_info = await validate_bot_token(
            token="123456789:TEST_TOKEN",
            http_client=http_client,
        )
        assert bot_info.id == 987654321
        assert bot_info.username == "test_hub_bot"
        assert bot_info.first_name == "Test Bot"
        assert bot_info.is_bot is True


@pytest.mark.asyncio
async def test_telegram_invalid_token_error():
    """Verifies 401 returns TelegramInvalidTokenError."""
    async def mock_handler(request: httpx.Request):
        return httpx.Response(
            401,
            json={
                "ok": False,
                "error_code": 401,
                "description": "Unauthorized",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        with pytest.raises(TelegramInvalidTokenError) as exc_info:
            await validate_bot_token("invalid:token", http_client=http_client)
        assert exc_info.value.error_code == 401


@pytest.mark.asyncio
async def test_telegram_rate_limit_error():
    """Verifies 429 returns TelegramRateLimitError with retry_after."""
    async def mock_handler(request: httpx.Request):
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 42",
                "parameters": {"retry_after": 42},
            },
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(token="123:token", http_client=http_client)
        with pytest.raises(TelegramRateLimitError) as exc_info:
            await client.send_message(chat_id=123, text="hello")
        assert exc_info.value.retry_after == 42


@pytest.mark.asyncio
async def test_telegram_forbidden_error():
    """Verifies 403 returns TelegramForbiddenError."""
    async def mock_handler(request: httpx.Request):
        return httpx.Response(
            403,
            json={
                "ok": False,
                "error_code": 403,
                "description": "Forbidden: bot was blocked by the user",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(token="123:token", http_client=http_client)
        with pytest.raises(TelegramForbiddenError):
            await client.send_message(chat_id=123, text="hello")
