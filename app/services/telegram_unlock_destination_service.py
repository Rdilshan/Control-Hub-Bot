"""Telegram Unlock Destination Service for deep-link generation and payload resolution."""

from typing import Optional
from app.exceptions import ValidationError


class TelegramUnlockDestinationService:
    """Handles Telegram deep links for video unlock flows (https://t.me/<bot>?start=unlock_<public_id>)."""

    UNLOCK_PREFIX = "unlock_"

    def build_destination(self, bot_username: str, video_public_id: str) -> str:
        """Builds a Telegram deep link URL for a video unlock destination.

        Args:
            bot_username: Username of the Client Bot.
            video_public_id: Public identifier of the video.

        Returns:
            Canonical Telegram deep link URL.
        """
        if not bot_username or not bot_username.strip():
            raise ValidationError("Client Bot username is required to build destination deep link")
        if not video_public_id or not video_public_id.strip():
            raise ValidationError("Video public ID is required to build destination deep link")

        clean_username = bot_username.strip().lstrip("@")
        clean_public_id = video_public_id.strip()
        return f"https://t.me/{clean_username}?start={self.UNLOCK_PREFIX}{clean_public_id}"

    def is_unlock_payload(self, payload: Optional[str]) -> bool:
        """Checks if a /start parameter is an unlock payload."""
        if not payload:
            return False
        return payload.strip().startswith(self.UNLOCK_PREFIX)

    def parse_payload(self, payload: Optional[str]) -> Optional[str]:
        """Extracts the video_public_id from an unlock payload string.

        Args:
            payload: Parameter string after /start.

        Returns:
            video_public_id if valid, or None if malformed/empty.
        """
        if not payload:
            return None
        cleaned = payload.strip()
        if not cleaned.startswith(self.UNLOCK_PREFIX):
            return None
        public_id = cleaned[len(self.UNLOCK_PREFIX):].strip()
        return public_id if public_id else None
