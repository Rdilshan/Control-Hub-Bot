"""Structured Logging Configuration with secret redaction and correlation ID context."""

import logging
import re
import sys
from typing import Optional
from contextvars import ContextVar

# Context variables for correlation/request tracing
request_id_ctx_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


class RedactingFormatter(logging.Formatter):
    """Logging formatter that automatically masks bot tokens and sensitive values."""

    # Regex pattern to match Telegram Bot Tokens (e.g. 123456789:ABCdefGHIjklMNOpqrsTUVwxyz)
    BOT_TOKEN_PATTERN = re.compile(r"(\d{8,12}:[A-Za-z0-9_-]{20,45})")
    
    # Password and secret key pattern
    SECRET_PATTERN = re.compile(r"(password|secret|key|token)=([^\s&]+)", re.IGNORECASE)

    def format(self, record: logging.LogRecord) -> str:
        # Add correlation ID to record if present
        request_id = request_id_ctx_var.get()
        record.request_id = request_id or "-"

        original_message = super().format(record)

        # Redact Telegram bot tokens
        redacted_message = self.BOT_TOKEN_PATTERN.sub(
            lambda m: f"{m.group(1).split(':')[0]}:***REDACTED***",
            original_message,
        )

        # Redact generic secrets
        redacted_message = self.SECRET_PATTERN.sub(
            r"\1=***REDACTED***",
            redacted_message,
        )

        return redacted_message


def setup_logging(log_level_name: str = "INFO") -> None:
    """Configures global application logging."""
    level = getattr(logging, log_level_name.upper(), logging.INFO)

    log_format = (
        "[%(asctime)s] [%(levelname)s] [req:%(request_id)s] [%(name)s:%(lineno)d]: %(message)s"
    )

    formatter = RedactingFormatter(fmt=log_format, datefmt="%Y-%m-%d %H:%M:%S")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(level)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove any existing handlers
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Set third party loggers to reasonable levels
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").addHandler(handler)
    logging.getLogger("uvicorn.error").handlers.clear()
    logging.getLogger("uvicorn.error").addHandler(handler)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Convenience getter for logger instances."""
    return logging.getLogger(name)


logger = get_logger("controlhub")

