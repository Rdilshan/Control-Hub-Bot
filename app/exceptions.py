"""Domain exception hierarchy and standard error representations."""

from typing import Any, Dict, Optional


class ApplicationError(Exception):
    """Base domain exception for all Control Hub application errors."""

    def __init__(
        self,
        message: str,
        code: str = "APPLICATION_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class ValidationError(ApplicationError):
    """Raised when input validation fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=422,
            details=details,
        )


class NotFoundError(ApplicationError):
    """Raised when an entity or resource is not found."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="NOT_FOUND",
            status_code=404,
            details=details,
        )


class UnauthorizedError(ApplicationError):
    """Raised when authentication credentials are missing or invalid."""

    def __init__(self, message: str = "Unauthorized", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            status_code=401,
            details=details,
        )


class ForbiddenError(ApplicationError):
    """Raised when the caller is authenticated but lacks required permissions."""

    def __init__(self, message: str = "Forbidden", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="FORBIDDEN",
            status_code=403,
            details=details,
        )


class ConflictError(ApplicationError):
    """Raised when an operation conflicts with existing state (e.g. duplicate bot)."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="CONFLICT",
            status_code=409,
            details=details,
        )


class ExternalServiceError(ApplicationError):
    """Raised when an upstream service (like Telegram API or Redis) encounters an error."""

    def __init__(
        self,
        message: str,
        code: str = "EXTERNAL_SERVICE_ERROR",
        status_code: int = 502,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            details=details,
        )


class TemporaryError(ApplicationError):
    """Raised when a temporary issue occurs that can be safely retried."""

    def __init__(
        self,
        message: str,
        code: str = "TEMPORARY_ERROR",
        status_code: int = 503,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            details=details,
        )


class UnlockifyError(ExternalServiceError):
    """Base exception for Unlockify provider interactions."""

    def __init__(
        self,
        message: str,
        code: str = "UNLOCKIFY_ERROR",
        status_code: int = 502,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, status_code=status_code, details=details)


class UnlockifyTimeoutError(UnlockifyError):
    """Raised when Unlockify request times out."""

    def __init__(self, message: str = "Unlockify request timed out", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="UNLOCKIFY_TIMEOUT", status_code=504, details=details)


class UnlockifyNetworkError(UnlockifyError):
    """Raised when network connection to Unlockify fails."""

    def __init__(self, message: str = "Network error communicating with Unlockify", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="UNLOCKIFY_NETWORK_ERROR", status_code=502, details=details)


class UnlockifyInvalidResponseError(UnlockifyError):
    """Raised when Unlockify returns unexpected or malformed response data."""

    def __init__(self, message: str = "Invalid response from Unlockify", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="UNLOCKIFY_INVALID_RESPONSE", status_code=502, details=details)


class UnlockifyRequestRejectedError(UnlockifyError):
    """Raised when Unlockify rejects request due to invalid input (HTTP 4xx)."""

    def __init__(self, message: str = "Unlockify rejected request", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="UNLOCKIFY_REJECTED_REQUEST", status_code=400, details=details)

