"""Unit tests for Client Admin /sponsor command and workflow."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ClientBotStatus
from app.db.models.client_bot import ClientBot
from app.db.models.sponsor_config import SponsorConfig
from app.telegram.client_bot.admin.sponsor import (
    apply_sponsor_url,
    handle_sponsor_callback,
    handle_sponsor_command,
)


@pytest.mark.asyncio
async def test_handle_sponsor_command_no_url(db_session: AsyncSession):
    bot = ClientBot(
        id=10,
        client_id=1,
        telegram_bot_id=1001,
        username="test_bot",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    telegram_client = MagicMock()
    telegram_client.send_message = AsyncMock(return_value={"ok": True})

    result = await handle_sponsor_command(
        client_bot_id=bot.id,
        telegram_user_id=12345,
        chat_id=12345,
        text="/sponsor",
        telegram_client=telegram_client,
        session=db_session,
    )

    assert result["ok"] is True
    assert result["action"] == "sponsor_dashboard_sent"
    telegram_client.send_message.assert_called_once()
    assert "Sponsor / Monetization Configuration" in telegram_client.send_message.call_args[1]["text"]


@pytest.mark.asyncio
async def test_handle_sponsor_command_with_url(db_session: AsyncSession):
    bot = ClientBot(
        id=11,
        client_id=1,
        telegram_bot_id=1002,
        username="test_bot_2",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    telegram_client = MagicMock()
    telegram_client.send_message = AsyncMock(return_value={"ok": True})

    result = await handle_sponsor_command(
        client_bot_id=bot.id,
        telegram_user_id=12345,
        chat_id=12345,
        text="/sponsor https://monetag.com/direct-link-123",
        telegram_client=telegram_client,
        session=db_session,
    )

    assert result["ok"] is True
    assert result["action"] == "sponsor_url_saved"
    telegram_client.send_message.assert_called_once()
    assert "Sponsor URL Saved & Enabled!" in telegram_client.send_message.call_args[1]["text"]


@pytest.mark.asyncio
async def test_handle_sponsor_callbacks(db_session: AsyncSession):
    bot = ClientBot(
        id=12,
        client_id=1,
        telegram_bot_id=1003,
        username="test_bot_3",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    sponsor = SponsorConfig(
        client_bot_id=bot.id,
        sponsor_url="https://sponsor.example.com",
        is_enabled=True,
    )
    db_session.add(sponsor)
    await db_session.flush()

    telegram_client = MagicMock()
    telegram_client.send_message = AsyncMock(return_value={"ok": True})

    # Disable
    res_disable = await handle_sponsor_callback(
        client_bot_id=bot.id,
        telegram_user_id=12345,
        chat_id=12345,
        callback_data="admin:sponsor:disable",
        telegram_client=telegram_client,
        session=db_session,
    )
    assert res_disable["ok"] is True
    assert res_disable["action"] == "sponsor_disabled"

    # Enable
    res_enable = await handle_sponsor_callback(
        client_bot_id=bot.id,
        telegram_user_id=12345,
        chat_id=12345,
        callback_data="admin:sponsor:enable",
        telegram_client=telegram_client,
        session=db_session,
    )
    assert res_enable["ok"] is True
    assert res_enable["action"] == "sponsor_enabled"
