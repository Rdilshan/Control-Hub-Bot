"""Unit tests for SecurityAuditService."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.enums import BotEventType
from app.security.audit import SecurityAuditService


@pytest.mark.asyncio
async def test_security_audit_service_records_events():
    mock_session = AsyncMock()
    service = SecurityAuditService(session=mock_session)
    service.repo = MagicMock()
    service.repo.record_event = AsyncMock()

    # Log Bot Connected
    await service.log_bot_connected(client_bot_id=1, telegram_user_id=123, bot_username="demo_bot")
    service.repo.record_event.assert_called_with(
        client_bot_id=1,
        event_type=BotEventType.BOT_CONNECTED,
        telegram_user_id=123,
        related_video_id=None,
        related_broadcast_id=None,
        metadata_json={"username": "demo_bot"},
    )

    # Log Bot Paused
    await service.log_bot_paused(client_bot_id=1, telegram_user_id=123, reason="Admin requested pause")
    service.repo.record_event.assert_called_with(
        client_bot_id=1,
        event_type=BotEventType.BOT_PAUSED,
        telegram_user_id=123,
        related_video_id=None,
        related_broadcast_id=None,
        metadata_json={"reason": "Admin requested pause"},
    )

    # Log Sponsor Changed
    await service.log_sponsor_changed(client_bot_id=1, telegram_user_id=123, sponsor_id=42)
    service.repo.record_event.assert_called_with(
        client_bot_id=1,
        event_type=BotEventType.SPONSOR_CHANGED,
        telegram_user_id=123,
        related_video_id=None,
        related_broadcast_id=None,
        metadata_json={"sponsor_id": 42},
    )
