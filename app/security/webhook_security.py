"""Webhook security verification service using constant-time digest comparison and payload checks."""

import hmac
import secrets
from typing import Any, Dict, Optional
from app.exceptions import ForbiddenError, ValidationError


class WebhookSecurityService:
    """Provides cryptographic verification of Telegram webhook secret tokens and payloads."""

    @staticmethod
    def generate_webhook_secret() -> str:
        """Generates a high-entropy cryptographically secure webhook secret token."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def generate_public_bot_id() -> str:
        """Generates a unique, non-secret public bot identifier for webhook routing."""
        return secrets.token_urlsafe(16)

    @staticmethod
    def verify_webhook_secret(received_secret: Optional[str], expected_secret: Optional[str]) -> bool:
        """Performs constant-time comparison of the incoming X-Telegram-Bot-Api-Secret-Token against expected secret."""
        if not received_secret or not expected_secret:
            return False
        return hmac.compare_digest(received_secret.strip(), expected_secret.strip())

    @staticmethod
    def validate_webhook_secret_header(received_secret: Optional[str], expected_secret: Optional[str]) -> None:
        """Enforces secret verification and raises ForbiddenError (403) on mismatch without leaking metadata."""
        if not WebhookSecurityService.verify_webhook_secret(received_secret, expected_secret):
            raise ForbiddenError("Invalid or missing webhook secret token.")

    @staticmethod
    def validate_webhook_payload(payload: Any) -> Dict[str, Any]:
        """Validates that the incoming update payload is a well-formed Telegram dictionary."""
        if not isinstance(payload, dict):
            raise ValidationError("Webhook payload must be a JSON object.")
        if "update_id" not in payload:
            raise ValidationError("Missing update_id in Telegram update payload.")
        return payload
