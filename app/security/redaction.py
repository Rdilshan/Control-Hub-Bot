"""Secret redaction service masking bot tokens, keys, and credentials in logs and outputs."""

import re
from typing import Any, Dict, List, Union


class SecretRedactionService:
    """Provides pattern-based and key-based secret masking and redaction."""

    # Regex matching Telegram bot tokens (e.g. 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ)
    BOT_TOKEN_PATTERN = re.compile(r"\b\d{6,16}:[A-Za-z0-9_-]{30,50}\b")

    # Sensitive dictionary keys to automatically mask
    SENSITIVE_KEYS = {
        "token",
        "bot_token",
        "token_encrypted",
        "webhook_secret",
        "webhook_secret_encrypted",
        "secret",
        "secret_token",
        "encryption_key",
        "password",
        "authorization",
        "api_key",
    }

    REDACTED_PLACEHOLDER = "[REDACTED]"

    @classmethod
    def redact_string(cls, text: str) -> str:
        """Replaces all bot tokens and secret patterns in a string with [REDACTED]."""
        if not text:
            return text
        return cls.BOT_TOKEN_PATTERN.sub(cls.REDACTED_PLACEHOLDER, str(text))

    @classmethod
    def mask_token(cls, token: str) -> str:
        """Returns a partially masked representation of a bot token (first 4 and last 4 chars), or [REDACTED]."""
        if not token or len(token) < 10:
            return cls.REDACTED_PLACEHOLDER
        return f"{token[:4]}********{token[-4:]}"

    @classmethod
    def redact_data(cls, data: Any) -> Any:
        """Recursively traverses dictionaries, lists, and strings to mask sensitive keys and token patterns."""
        if isinstance(data, dict):
            redacted_dict: Dict[str, Any] = {}
            for k, v in data.items():
                if str(k).lower() in cls.SENSITIVE_KEYS:
                    redacted_dict[k] = cls.REDACTED_PLACEHOLDER
                else:
                    redacted_dict[k] = cls.redact_data(v)
            return redacted_dict

        if isinstance(data, list):
            return [cls.redact_data(item) for item in data]

        if isinstance(data, tuple):
            return tuple(cls.redact_data(item) for item in data)

        if isinstance(data, str):
            return cls.redact_string(data)

        return data
