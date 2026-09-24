"""Client Bot Runtime Context representations."""

from dataclasses import dataclass
from typing import Optional
from app.core.enums import ClientBotStatus


@dataclass(frozen=True)
class ClientBotContext:
    """Runtime context for an active Client Bot."""
    client_bot_id: int
    client_id: int
    telegram_bot_id: int
    bot_username: Optional[str]
    display_name: Optional[str]
    status: ClientBotStatus
    public_bot_id: str
    owner_telegram_user_id: Optional[int] = None

    def __repr__(self) -> str:
        return (
            f"ClientBotContext(bot_id={self.client_bot_id}, "
            f"username=@{self.bot_username or 'unknown'}, "
            f"status={self.status.value if hasattr(self.status, 'value') else self.status})"
        )


@dataclass(frozen=True)
class ClientBotActorContext:
    """Runtime context for an actor interacting with a Client Bot."""
    telegram_user_id: int
    chat_id: int
    chat_type: str
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    language_code: Optional[str]
    role: str  # "ADMIN" or "VIEWER"
    admin_record_id: Optional[int] = None
    viewer_record_id: Optional[int] = None
