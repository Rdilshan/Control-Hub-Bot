"""Telegram integration types and identity data models."""

from dataclasses import dataclass
from typing import Optional
from app.core.enums import BotType


@dataclass
class TelegramBotInfo:
    """Represents public metadata returned by Telegram getMe API."""
    id: int
    is_bot: bool
    first_name: str
    username: Optional[str] = None
    can_join_groups: Optional[bool] = None
    can_read_all_group_messages: Optional[bool] = None
    supports_inline_queries: Optional[bool] = None


@dataclass
class BotContext:
    """Represents runtime context for a Telegram Bot (Control Hub or Client Bot)."""
    bot_type: BotType
    platform_bot_id: Optional[int] = None
    telegram_bot_id: Optional[int] = None
    username: Optional[str] = None
    client_id: Optional[int] = None
    token: Optional[str] = None
