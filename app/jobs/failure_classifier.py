"""Job Failure Classifier and Error Normalization."""

from dataclasses import dataclass
from typing import Optional
from app.core.enums import ErrorClassification, ErrorCode
from app.exceptions import (
    BotDisconnectedException,
    BotPausedException,
    ControlHubError,
    InvalidBotTokenException,
    SponsorNotConfiguredException,
    UnlockifyTimeoutException,
    VideoNotReadyException,
)


@dataclass
class FailureDetails:
    classification: ErrorClassification
    error_code: ErrorCode
    safe_message: str
    retry_after: Optional[int] = None
    is_retryable: bool = False


class JobFailureClassifier:
    @staticmethod
    def classify(exc: Exception) -> FailureDetails:
        """Classifies any exception into standardized ErrorClassification, ErrorCode, and safe message."""
        msg = str(exc)
        exc_type = exc.__class__.__name__

        # 1. Telegram Rate Limits (429)
        if "TelegramRetryAfter" in exc_type or "retry after" in msg.lower() or "429" in msg:
            retry_after = getattr(exc, "retry_after", None)
            if retry_after is None:
                # Try to parse digits from message if present
                import re
                match = re.search(r"retry after (\d+)", msg.lower())
                if match:
                    retry_after = int(match.group(1))
                else:
                    retry_after = 5
            return FailureDetails(
                classification=ErrorClassification.RATE_LIMITED,
                error_code=ErrorCode.TELEGRAM_RATE_LIMIT,
                safe_message=f"Telegram rate limit hit. Backing off for {retry_after}s.",
                retry_after=retry_after,
                is_retryable=True,
            )

        # 2. Telegram Forbidden / User Blocked
        if (
            "TelegramForbiddenError" in exc_type
            or "bot was blocked by the user" in msg.lower()
            or "user is deactivated" in msg.lower()
            or "chat not found" in msg.lower()
            or "forbidden" in msg.lower()
        ):
            return FailureDetails(
                classification=ErrorClassification.BLOCKED_USER,
                error_code=ErrorCode.TELEGRAM_FORBIDDEN,
                safe_message="Recipient user blocked the bot or chat was not found.",
                is_retryable=False,
            )

        # 3. Credential / Unauthorized Failures
        if (
            isinstance(exc, InvalidBotTokenException)
            or "TelegramUnauthorizedError" in exc_type
            or "unauthorized" in msg.lower()
            or "invalid bot token" in msg.lower()
            or "token is invalid" in msg.lower()
        ):
            return FailureDetails(
                classification=ErrorClassification.CREDENTIAL_FAILURE,
                error_code=ErrorCode.INVALID_TOKEN,
                safe_message="Bot token is invalid or has been revoked.",
                is_retryable=False,
            )

        # 4. Bot Lifecycle: Paused / Disconnected
        if isinstance(exc, BotPausedException) or "bot is paused" in msg.lower():
            return FailureDetails(
                classification=ErrorClassification.PAUSE_REQUIRED,
                error_code=ErrorCode.BOT_PAUSED,
                safe_message="Client Bot is paused. Dependent tasks are paused.",
                is_retryable=False,
            )

        if isinstance(exc, BotDisconnectedException) or "bot is disconnected" in msg.lower():
            return FailureDetails(
                classification=ErrorClassification.PAUSE_REQUIRED,
                error_code=ErrorCode.BOT_DISCONNECTED,
                safe_message="Client Bot is disconnected.",
                is_retryable=False,
            )

        # 5. Unlockify Provider Errors
        if isinstance(exc, UnlockifyTimeoutException) or "timeout" in msg.lower() or "connecttimeout" in msg.lower():
            return FailureDetails(
                classification=ErrorClassification.RETRYABLE,
                error_code=ErrorCode.UNLOCKIFY_TIMEOUT,
                safe_message="Unlockify link creation timed out.",
                is_retryable=True,
            )

        if "unlockify" in msg.lower():
            if "invalid response" in msg.lower() or "malformed" in msg.lower():
                return FailureDetails(
                    classification=ErrorClassification.NON_RETRYABLE,
                    error_code=ErrorCode.UNLOCKIFY_INVALID_RESPONSE,
                    safe_message="Unlockify returned an invalid response.",
                    is_retryable=False,
                )
            if "400" in msg or "bad request" in msg.lower():
                return FailureDetails(
                    classification=ErrorClassification.NON_RETRYABLE,
                    error_code=ErrorCode.UNLOCKIFY_HTTP_ERROR,
                    safe_message="Unlockify rejected request with 400 Bad Request.",
                    is_retryable=False,
                )
            if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
                return FailureDetails(
                    classification=ErrorClassification.RETRYABLE,
                    error_code=ErrorCode.UNLOCKIFY_HTTP_ERROR,
                    safe_message="Unlockify provider server error (5xx).",
                    is_retryable=True,
                )

        # 6. Database and Storage Errors
        if "IntegrityError" in exc_type or "foreign key" in msg.lower() or "unique constraint" in msg.lower():
            return FailureDetails(
                classification=ErrorClassification.DATA_INTEGRITY_FAILURE,
                error_code=ErrorCode.DATABASE_INTEGRITY_ERROR,
                safe_message="Database integrity constraint violation.",
                is_retryable=False,
            )

        if "OperationalError" in exc_type or "database is locked" in msg.lower() or "connection closed" in msg.lower():
            return FailureDetails(
                classification=ErrorClassification.RETRYABLE,
                error_code=ErrorCode.DATABASE_TEMPORARY_ERROR,
                safe_message="Temporary database connectivity issue.",
                is_retryable=True,
            )

        # 7. Redis / Queue Broker Errors
        if "RedisError" in exc_type or "ConnectionError" in exc_type or "redis" in msg.lower():
            return FailureDetails(
                classification=ErrorClassification.RETRYABLE,
                error_code=ErrorCode.REDIS_UNAVAILABLE,
                safe_message="Queue broker temporarily unavailable.",
                is_retryable=True,
            )

        # 8. Business Validation Failures
        if isinstance(exc, SponsorNotConfiguredException):
            return FailureDetails(
                classification=ErrorClassification.NON_RETRYABLE,
                error_code=ErrorCode.SPONSOR_NOT_CONFIGURED,
                safe_message="Sponsor is not configured for this bot.",
                is_retryable=False,
            )

        if isinstance(exc, VideoNotReadyException):
            return FailureDetails(
                classification=ErrorClassification.NON_RETRYABLE,
                error_code=ErrorCode.VIDEO_NOT_READY,
                safe_message="Video is not in READY state.",
                is_retryable=False,
            )

        # 9. Generic Telegram Network / 5xx
        if "TelegramNetworkError" in exc_type or "telegram" in msg.lower():
            if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
                return FailureDetails(
                    classification=ErrorClassification.RETRYABLE,
                    error_code=ErrorCode.TELEGRAM_SERVER_ERROR,
                    safe_message="Telegram API server error (5xx).",
                    is_retryable=True,
                )
            return FailureDetails(
                classification=ErrorClassification.RETRYABLE,
                error_code=ErrorCode.TELEGRAM_NETWORK_ERROR,
                safe_message="Telegram network communication error.",
                is_retryable=True,
            )

        # 10. Default / Unknown
        return FailureDetails(
            classification=ErrorClassification.UNKNOWN,
            error_code=ErrorCode.UNKNOWN_ERROR,
            safe_message="An unexpected background task error occurred.",
            is_retryable=True,  # Unknown exceptions retry up to max_attempts
        )
