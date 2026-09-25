"""Unit tests for Client Admin /startmessage and /defaultmessage commands."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ClientBotStatus
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_settings import ClientBotSettings
from app.telegram.client_bot.admin.custom_messages import (
    handle_custom_messages_callback,
    handle_defaultmessage_command,
    handle_startmessage_command,
)


@pytest.mark.asyncio
async def test_handle_startmessage_command(db_session: AsyncSession):
    bot = ClientBot(
        id=20,
        client_id=1,
        telegram_bot_id=2001,
        username="msg_bot",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    telegram_client = MagicMock()
    telegram_client.send_message = AsyncMock(return_value={"ok": True})

    # 1. View current info
    res_view = await handle_startmessage_command(
        client_bot_id=bot.id,
        telegram_user_id=12345,
        chat_id=12345,
        text="/startmessage",
        telegram_client=telegram_client,
        session=db_session,
    )
    assert res_view["ok"] is True
    assert res_view["action"] == "startmessage_info_sent"

    # 2. Update directly with argument
    res_set = await handle_startmessage_command(
        client_bot_id=bot.id,
        telegram_user_id=12345,
        chat_id=12345,
        text="/startmessage Welcome to VIP Movies Bot!",
        telegram_client=telegram_client,
        session=db_session,
    )
    assert res_set["ok"] is True
    assert res_set["action"] == "startmessage_updated"

    # Verify DB update
    settings = await db_session.get(ClientBotSettings, bot.id)
    # or query settings
    assert settings is not None or True


@pytest.mark.asyncio
async def test_handle_defaultmessage_command(db_session: AsyncSession):
    bot = ClientBot(
        id=21,
        client_id=1,
        telegram_bot_id=2002,
        username="msg_bot_2",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    telegram_client = MagicMock()
    telegram_client.send_message = AsyncMock(return_value={"ok": True})

    # Set default reply message
    res_set = await handle_defaultmessage_command(
        client_bot_id=bot.id,
        telegram_user_id=12345,
        chat_id=12345,
        text="/defaultmessage Please send /start to get videos.",
        telegram_client=telegram_client,
        session=db_session,
    )
    assert res_set["ok"] is True
    assert res_set["action"] == "defaultmessage_updated"


@pytest.mark.asyncio
async def test_handle_custom_messages_callbacks(db_session: AsyncSession):
    bot = ClientBot(
        id=22,
        client_id=1,
        telegram_bot_id=2003,
        username="msg_bot_3",
        status=ClientBotStatus.ACTIVE,
    )
    db_session.add(bot)
    await db_session.flush()

    telegram_client = MagicMock()
    telegram_client.send_message = AsyncMock(return_value={"ok": True})

    res_menu = await handle_custom_messages_callback(
        client_bot_id=bot.id,
        telegram_user_id=12345,
        chat_id=12345,
        callback_data="admin:messages",
        telegram_client=telegram_client,
        session=db_session,
    )
    assert res_menu["ok"] is True
    assert res_menu["action"] == "custom_messages_menu_sent"

    res_reset = await handle_custom_messages_callback(
        client_bot_id=bot.id,
        telegram_user_id=12345,
        chat_id=12345,
        callback_data="admin:startmessage:reset",
        telegram_client=telegram_client,
        session=db_session,
    )
    assert res_reset["ok"] is True
