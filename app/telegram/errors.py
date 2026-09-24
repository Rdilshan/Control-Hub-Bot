"""Telegram API specific exception types."""

from typing import Optional
from app.exceptions import ExternalServiceError


class TelegramAPIError(ExternalServiceError):
    """Base exception for Telegram Bot API errors."""

    def __init__(
        self,
        message: str,
        code: str = "TELEGRAM_API_ERROR",
        status_code: int = 502,
        error_code: Optional[int] = None,
        description: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            details={"error_code": error_code, "description": description},
        )
        self.error_code = error_code
        self.description = description


class TelegramInvalidTokenError(TelegramAPIError):
    """Raised when Telegram Bot Token is malformed or rejected (401 / 404)."""

    def __init__(self, message: str = "Invalid Telegram Bot Token", description: Optional[str] = None):
        super().__init__(
            message=message,
            code="TELEGRAM_INVALID_TOKEN",
            status_code=400,
            error_code=401,
            description=description,
        )


class TelegramRateLimitError(TelegramAPIError):
    """Raised when Telegram returns 429 Too Many Requests."""

    def __init__(
        self,
        message: str = "Telegram rate limit exceeded",
        retry_after: int = 30,
        description: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            code="TELEGRAM_RATE_LIMIT",
            status_code=429,
            error_code=429,
            description=description,
        )
        self.retry_after = retry_after
        self.details["retry_after"] = retry_after


class TelegramForbiddenError(TelegramAPIError):
    """Raised when bot is blocked by user, kicked from group, or deactivated (403)."""

    def __init__(
        self,
        message: str = "Telegram bot action forbidden",
        description: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            code="TELEGRAM_FORBIDDEN",
            status_code=403,
            error_code=403,
            description=description,
        )


class TelegramNetworkError(TelegramAPIError):
    """Raised when network or timeout issues occur while reaching Telegram."""

    def __init__(
        self,
        message: str = "Network error connecting to Telegram API",
        description: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            code="TELEGRAM_NETWORK_ERROR",
            status_code=504,
            description=description,
        )
