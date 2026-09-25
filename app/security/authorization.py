"""Authorization service and guards enforcing server-side role and tenant access."""

from typing import Optional, Union
from app.config import get_settings
from app.core.enums import BotStatus
from app.exceptions import (
    ForbiddenError,
    UnauthorizedError,
    NotFoundError,
    BotPausedException,
    BotDisconnectedException,
)


class AuthorizationService:
    """Service providing server-side authorization checks for platform owners, clients, admins, and viewers."""

    def __init__(self, platform_owner_id: Optional[int] = None):
        settings = get_settings()
        self._platform_owner_id = platform_owner_id or settings.PLATFORM_OWNER_TELEGRAM_ID

    def is_platform_owner(self, telegram_user_id: int) -> bool:
        """Returns True if the given telegram_user_id matches the configured Platform Owner ID."""
        if not self._platform_owner_id:
            return False
        return int(telegram_user_id) == int(self._platform_owner_id)

    def require_platform_owner(self, telegram_user_id: int) -> None:
        """Enforces that the caller is the Platform Owner. Raises ForbiddenError otherwise."""
        if not self.is_platform_owner(telegram_user_id):
            raise ForbiddenError("Platform owner privileges required.", details={"user_id": telegram_user_id})

    def require_client(self, telegram_user_id: int, client: Optional[object]) -> None:
        """Enforces that a registered client exists for the Telegram user ID."""
        if not client:
            raise UnauthorizedError("Client account not found.", details={"user_id": telegram_user_id})

    def require_client_bot_owner(self, client_id: int, client_bot: Optional[object]) -> None:
        """Enforces that the Client owns the target ClientBot. Raises ForbiddenError if ownership mismatch."""
        if not client_bot:
            raise NotFoundError("Bot not found.")
        bot_client_id = getattr(client_bot, "client_id", None)
        if bot_client_id is None or int(bot_client_id) != int(client_id):
            raise ForbiddenError("Access denied: you do not own this bot.")

    def require_client_bot_admin(
        self,
        telegram_user_id: int,
        client_bot: Optional[object],
        is_admin: bool,
    ) -> None:
        """Enforces that the Telegram user is an authorized admin for the specified ClientBot."""
        if not client_bot:
            raise NotFoundError("Bot not found.")
        if not is_admin:
            raise ForbiddenError("Client bot admin privileges required.", details={"user_id": telegram_user_id})

    def require_active_client_bot(self, client_bot: Optional[object]) -> None:
        """Enforces that the ClientBot is in ACTIVE status and ready to serve traffic."""
        if not client_bot:
            raise NotFoundError("Bot not found.")
        status = getattr(client_bot, "status", None)
        status_val = status.value if hasattr(status, "value") else str(status)
        bot_id = getattr(client_bot, "id", None)

        if status_val == BotStatus.PAUSED.value:
            raise BotPausedException(bot_id=bot_id)
        if status_val in (BotStatus.DISCONNECTED.value, BotStatus.PROVISIONING.value, BotStatus.REVOKED.value):
            raise BotDisconnectedException(bot_id=bot_id)
        if status_val != BotStatus.ACTIVE.value:
            raise ForbiddenError(f"Bot is not active (current status: {status_val})", details={"bot_id": bot_id})
