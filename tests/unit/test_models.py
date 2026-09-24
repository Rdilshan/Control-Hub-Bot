"""Unit tests for models, schema serialization, token encryption, and enums."""

from app.core.enums import (
    BotAdminRole,
    BotEventType,
    BroadcastStatus,
    CatchupStatus,
    ClientBotStatus,
    ClientStatus,
    DeliveryStatus,
    JobStatus,
    JobType,
    ProcessingStatus,
    UnlockLinkStatus,
    VideoStatus,
    ViewerStatus,
)
from app.core.security import decrypt_token, encrypt_token, mask_bot_token


def test_token_encryption_and_decryption():
    raw_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz_secret_token"
    encrypted = encrypt_token(raw_token)
    assert encrypted is not None
    assert encrypted != raw_token
    assert "ABCdef" not in encrypted

    decrypted = decrypt_token(encrypted)
    assert decrypted == raw_token


def test_enums_values():
    assert ClientStatus.ACTIVE == "ACTIVE"
    assert ClientBotStatus.PAUSED == "PAUSED"
    assert BotAdminRole.OWNER == "OWNER"
    assert ViewerStatus.BLOCKED == "BLOCKED"
    assert VideoStatus.READY == "READY"
    assert ProcessingStatus.PENDING == "PENDING"
    assert UnlockLinkStatus.ACTIVE == "ACTIVE"
    assert BroadcastStatus.COMPLETED == "COMPLETED"
    assert DeliveryStatus.SENT == "SENT"
    assert CatchupStatus.SENT == "SENT"
    assert JobType.VIDEO_PROCESS == "VIDEO_PROCESS"
    assert JobStatus.RUNNING == "RUNNING"
    assert BotEventType.BOT_CONNECTED == "BOT_CONNECTED"
