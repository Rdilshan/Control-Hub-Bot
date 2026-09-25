"""Input validation and sanitization service for URLs, messages, bot tokens, and parameters."""

import re
from urllib.parse import urlparse
from typing import Optional
from app.exceptions import ValidationError


class InputValidationService:
    """Provides validation and sanitization for external and user-submitted inputs."""

    # Standard Telegram bot token regex: <bot_id>:<token_secret>
    BOT_TOKEN_REGEX = re.compile(r"^\d{6,16}:[A-Za-z0-9_-]{30,50}$")

    # Allowed URL schemes
    ALLOWED_URL_SCHEMES = {"http", "https"}

    @classmethod
    def validate_sponsor_url(cls, url: Optional[str], max_length: int = 2048) -> str:
        """Validates sponsor URL against strict HTTP/HTTPS scheme, length, and host structure.

        Rejects dangerous schemes such as javascript:, file:, data:, ftp:.
        """
        if not url:
            raise ValidationError("Sponsor URL cannot be empty.")

        cleaned_url = url.strip()
        if len(cleaned_url) > max_length:
            raise ValidationError(f"Sponsor URL exceeds maximum allowed length of {max_length} characters.")

        # Check for control characters
        if any(ord(c) < 32 or ord(c) == 127 for c in cleaned_url):
            raise ValidationError("Sponsor URL contains invalid control characters.")

        try:
            parsed = urlparse(cleaned_url)
        except Exception as e:
            raise ValidationError(f"Invalid URL structure: {e}") from e

        if not parsed.scheme or parsed.scheme.lower() not in cls.ALLOWED_URL_SCHEMES:
            raise ValidationError(f"Invalid URL scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted.")

        if not parsed.netloc:
            raise ValidationError("Sponsor URL must contain a valid domain host.")

        # Block localhost / private IP tricks if needed
        host = parsed.hostname.lower() if parsed.hostname else ""
        if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
            raise ValidationError("Sponsor URL cannot point to localhost.")

        return cleaned_url

    @classmethod
    def validate_start_message(cls, text: Optional[str], max_length: int = 3000) -> str:
        """Validates custom start message content and bounds."""
        if not text:
            raise ValidationError("Start message cannot be empty.")
        cleaned = text.strip()
        if len(cleaned) > max_length:
            raise ValidationError(f"Start message exceeds maximum length of {max_length} characters.")
        return cleaned

    @classmethod
    def validate_default_message(cls, text: Optional[str], max_length: int = 3000) -> str:
        """Validates custom default message content and bounds."""
        if not text:
            raise ValidationError("Default message cannot be empty.")
        cleaned = text.strip()
        if len(cleaned) > max_length:
            raise ValidationError(f"Default message exceeds maximum length of {max_length} characters.")
        return cleaned

    @classmethod
    def validate_video_title(cls, title: Optional[str], max_length: int = 255) -> str:
        """Validates video title."""
        if not title:
            return "Untitled Video"
        cleaned = title.strip()
        if len(cleaned) > max_length:
            return cleaned[:max_length]
        return cleaned

    @classmethod
    def validate_bot_token_format(cls, token: Optional[str]) -> bool:
        """Validates the structural format of a Telegram bot token (regex pre-check)."""
        if not token or not isinstance(token, str):
            return False
        return bool(cls.BOT_TOKEN_REGEX.match(token.strip()))

    @classmethod
    def sanitize_text(cls, text: Optional[str]) -> str:
        """Strips leading/trailing whitespace and removes ASCII control characters."""
        if not text:
            return ""
        # Remove null bytes and non-printable control characters except newline and tab
        return "".join(c for c in text.strip() if c in ("\n", "\t", "\r") or ord(c) >= 32)
