"""Database and domain status enums."""

from enum import Enum


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class BotType(str, Enum):
    CONTROL_HUB = "CONTROL_HUB"
    CLIENT_BOT = "CLIENT_BOT"


class ControlHubRole(str, Enum):
    PLATFORM_OWNER = "PLATFORM_OWNER"
    CLIENT = "CLIENT"
    NEW_CLIENT = "NEW_CLIENT"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"


class ClientBotStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DISCONNECTED = "DISCONNECTED"
    INVALID_TOKEN = "INVALID_TOKEN"
    PROVISION_FAILED = "PROVISION_FAILED"


class BotAdminRole(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"


class ViewerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    INACTIVE = "INACTIVE"


class VideoStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


class ProcessingStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSING_THUMBNAIL = "PROCESSING_THUMBNAIL"
    CREATING_UNLOCK_LINK = "CREATING_UNLOCK_LINK"
    READY = "READY"
    FAILED = "FAILED"


class UnlockLinkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    FAILED = "FAILED"


class BroadcastStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class CatchupStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class JobType(str, Enum):
    CLIENT_BOT_PROVISION = "CLIENT_BOT_PROVISION"
    CLIENT_BOT_DISCONNECT = "CLIENT_BOT_DISCONNECT"
    VIDEO_PROCESS = "VIDEO_PROCESS"
    CREATE_UNLOCK_LINK = "CREATE_UNLOCK_LINK"
    BROADCAST = "BROADCAST"
    CATCHUP = "CATCHUP"
    RETRY = "RETRY"
    UNLOCK_VIDEO_DELIVERY = "UNLOCK_VIDEO_DELIVERY"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"


class BotEventType(str, Enum):
    BOT_CONNECTION_STARTED = "BOT_CONNECTION_STARTED"
    BOT_CONNECTED = "BOT_CONNECTED"
    BOT_CONNECTION_FAILED = "BOT_CONNECTION_FAILED"
    BOT_RECONNECTED = "BOT_RECONNECTED"
    BOT_PAUSED = "BOT_PAUSED"
    BOT_RESUMED = "BOT_RESUMED"
    BOT_DISCONNECTED = "BOT_DISCONNECTED"
    BOT_TOKEN_INVALIDATED = "BOT_TOKEN_INVALIDATED"
    VIEWER_STARTED = "VIEWER_STARTED"
    VIDEO_CREATED = "VIDEO_CREATED"
    VIDEO_READY = "VIDEO_READY"
    BROADCAST_STARTED = "BROADCAST_STARTED"
    BROADCAST_COMPLETED = "BROADCAST_COMPLETED"
    VIDEO_DELIVERED_AFTER_UNLOCK = "VIDEO_DELIVERED_AFTER_UNLOCK"


def enum_val(v: object) -> str:
    """Safely extracts string representation from either an Enum instance or a string."""
    if v is None:
        return ""
    if hasattr(v, "value"):
        return str(v.value)
    return str(v)

