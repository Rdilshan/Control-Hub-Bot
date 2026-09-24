"""Lifecycle Capability Service defining operations allowed per Client Bot state."""

from app.core.enums import ClientBotStatus, enum_val


class LifecycleCapabilityService:
    """Centralized capability validation matrix for Client Bot lifecycle states."""

    @staticmethod
    def _get_status_str(status: object) -> str:
        return enum_val(status)

    @classmethod
    def can_admin_read(cls, status: object) -> bool:
        """Determines if admin read-only operations (/stats, /videos, /processing, etc.) are allowed."""
        s = cls._get_status_str(status)
        return s in (ClientBotStatus.ACTIVE.value, ClientBotStatus.PAUSED.value)

    @classmethod
    def can_admin_write(cls, status: object) -> bool:
        """Determines if admin write/modification operations (/createvideo, /sponsor, etc.) are allowed."""
        s = cls._get_status_str(status)
        return s == ClientBotStatus.ACTIVE.value

    @classmethod
    def can_viewer_start(cls, status: object) -> bool:
        """Determines if viewer normal /start workflow is allowed."""
        s = cls._get_status_str(status)
        return s == ClientBotStatus.ACTIVE.value

    @classmethod
    def can_create_video(cls, status: object) -> bool:
        """Determines if video ingestion (/createvideo) is allowed."""
        s = cls._get_status_str(status)
        return s == ClientBotStatus.ACTIVE.value

    @classmethod
    def can_process_video(cls, status: object, requires_telegram: bool = False) -> bool:
        """Determines if video processing stage is allowed."""
        s = cls._get_status_str(status)
        if requires_telegram:
            return s == ClientBotStatus.ACTIVE.value
        # Non-telegram stages (e.g. Unlockify link generation) can complete while PAUSED or UNAVAILABLE
        return s in (
            ClientBotStatus.ACTIVE.value,
            ClientBotStatus.PAUSED.value,
            ClientBotStatus.UNAVAILABLE.value,
        )

    @classmethod
    def can_broadcast(cls, status: object) -> bool:
        """Determines if LIVE broadcast sending to viewers is allowed."""
        s = cls._get_status_str(status)
        return s == ClientBotStatus.ACTIVE.value

    @classmethod
    def can_catchup(cls, status: object) -> bool:
        """Determines if historical video catch-up sending is allowed."""
        s = cls._get_status_str(status)
        return s == ClientBotStatus.ACTIVE.value

    @classmethod
    def can_unlock_delivery(cls, status: object) -> bool:
        """Determines if actual video delivery after unlock completion is allowed."""
        s = cls._get_status_str(status)
        return s == ClientBotStatus.ACTIVE.value

    @classmethod
    def is_paused(cls, status: object) -> bool:
        """Checks if bot is currently in PAUSED status."""
        s = cls._get_status_str(status)
        return s == ClientBotStatus.PAUSED.value

    @classmethod
    def is_disconnected(cls, status: object) -> bool:
        """Checks if bot is currently in DISCONNECTED status."""
        s = cls._get_status_str(status)
        return s == ClientBotStatus.DISCONNECTED.value
