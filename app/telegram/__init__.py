"""Telegram integration package."""

from app.telegram.client import TelegramClient, validate_bot_token
from app.telegram.errors import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramInvalidTokenError,
    TelegramNetworkError,
    TelegramRateLimitError,
)
from app.telegram.types import BotContext, TelegramBotInfo

__all__ = [
    "TelegramClient",
    "validate_bot_token",
    "TelegramBotInfo",
    "BotContext",
    "TelegramAPIError",
    "TelegramInvalidTokenError",
    "TelegramRateLimitError",
    "TelegramForbiddenError",
    "TelegramNetworkError",
]
