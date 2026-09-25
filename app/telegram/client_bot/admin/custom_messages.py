"""Client Admin custom start and default messages configuration handler."""

import asyncio
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.client_bot_settings import ClientBotSettings
from app.logging_config import get_logger
from app.redis.client import get_redis
from app.repositories.client_bot_settings import ClientBotSettingsRepository
from app.telegram.client import TelegramClient

logger = get_logger(__name__)

MESSAGES_STATE_PREFIX = "controlhub:clientbot:messages_state:"
MESSAGES_STATE_TTL = 1800  # 30 minutes
WAITING_FOR_START_MESSAGE = "WAITING_FOR_START_MESSAGE"
WAITING_FOR_DEFAULT_MESSAGE = "WAITING_FOR_DEFAULT_MESSAGE"

_in_memory_messages_state: Dict[str, str] = {}
_messages_lock = asyncio.Lock()


async def get_messages_state(client_bot_id: int, telegram_user_id: int) -> Optional[str]:
    key = f"{MESSAGES_STATE_PREFIX}{client_bot_id}:{telegram_user_id}"
    try:
        redis = get_redis()
        return await redis.get(key)
    except Exception:
        async with _messages_lock:
            return _in_memory_messages_state.get(key)


async def set_messages_state(client_bot_id: int, telegram_user_id: int, state: str) -> None:
    key = f"{MESSAGES_STATE_PREFIX}{client_bot_id}:{telegram_user_id}"
    try:
        redis = get_redis()
        await redis.set(key, state, ex=MESSAGES_STATE_TTL)
    except Exception:
        async with _messages_lock:
            _in_memory_messages_state[key] = state


async def clear_messages_state(client_bot_id: int, telegram_user_id: int) -> None:
    key = f"{MESSAGES_STATE_PREFIX}{client_bot_id}:{telegram_user_id}"
    try:
        redis = get_redis()
        await redis.delete(key)
    except Exception:
        async with _messages_lock:
            _in_memory_messages_state.pop(key, None)


async def _get_or_create_settings(repo: ClientBotSettingsRepository, client_bot_id: int) -> ClientBotSettings:
    settings = await repo.get_by_bot_id(client_bot_id)
    if not settings:
        settings = ClientBotSettings(
            client_bot_id=client_bot_id,
            start_message=None,
            default_message=None,
        )
        repo.session.add(settings)
        await repo.session.flush()
    return settings


async def handle_startmessage_command(
    client_bot_id: int,
    telegram_user_id: int,
    chat_id: int,
    text: str,
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Handles /startmessage command."""
    repo = ClientBotSettingsRepository(session)
    settings = await _get_or_create_settings(repo, client_bot_id)
    parts = text.strip().split(maxsplit=1)

    if len(parts) > 1 and parts[1].strip():
        new_msg = parts[1].strip()
        settings.start_message = new_msg
        await session.flush()
        await clear_messages_state(client_bot_id, telegram_user_id)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=f"✅ <b>Custom Start Message Updated!</b>\n\n<b>New Message:</b>\n{new_msg}",
            reply_markup={"inline_keyboard": [
                [{"text": "💬 Custom Messages Menu", "callback_data": "admin:messages"}],
                [{"text": "🏠 Dashboard", "callback_data": "admin:dashboard"}],
            ]},
        )
        return {"ok": True, "action": "startmessage_updated"}

    current = settings.start_message or "<i>Default system welcome message</i>"
    await telegram_client.send_message(
        chat_id=chat_id,
        text=(
            f"💬 <b>Custom Start Message</b>\n\n"
            f"Shown to new viewers when they first send <code>/start</code>.\n\n"
            f"<b>Current Start Message:</b>\n{current}\n\n"
            f"<i>To change, reply with your new message or use:</i>\n"
            f"<code>/startmessage &lt;your custom text&gt;</code>"
        ),
        reply_markup={"inline_keyboard": [
            [{"text": "✏️ Change Start Message", "callback_data": "admin:startmessage:set"}],
            [{"text": "🔄 Reset to Default", "callback_data": "admin:startmessage:reset"}],
            [{"text": "🏠 Dashboard", "callback_data": "admin:dashboard"}],
        ]},
    )
    return {"ok": True, "action": "startmessage_info_sent"}


async def handle_defaultmessage_command(
    client_bot_id: int,
    telegram_user_id: int,
    chat_id: int,
    text: str,
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Handles /defaultmessage command."""
    repo = ClientBotSettingsRepository(session)
    settings = await _get_or_create_settings(repo, client_bot_id)
    parts = text.strip().split(maxsplit=1)

    if len(parts) > 1 and parts[1].strip():
        new_msg = parts[1].strip()
        settings.default_message = new_msg
        await session.flush()
        await clear_messages_state(client_bot_id, telegram_user_id)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=f"✅ <b>Custom Default Reply Message Updated!</b>\n\n<b>New Message:</b>\n{new_msg}",
            reply_markup={"inline_keyboard": [
                [{"text": "💬 Custom Messages Menu", "callback_data": "admin:messages"}],
                [{"text": "🏠 Dashboard", "callback_data": "admin:dashboard"}],
            ]},
        )
        return {"ok": True, "action": "defaultmessage_updated"}

    current = settings.default_message or "<i>Default fallback response message</i>"
    await telegram_client.send_message(
        chat_id=chat_id,
        text=(
            f"🔁 <b>Custom Default Reply Message</b>\n\n"
            f"Shown to viewers when they send unhandled text or commands.\n\n"
            f"<b>Current Default Message:</b>\n{current}\n\n"
            f"<i>To change, reply with your new message or use:</i>\n"
            f"<code>/defaultmessage &lt;your custom text&gt;</code>"
        ),
        reply_markup={"inline_keyboard": [
            [{"text": "✏️ Change Default Reply", "callback_data": "admin:defaultmessage:set"}],
            [{"text": "🔄 Reset to Default", "callback_data": "admin:defaultmessage:reset"}],
            [{"text": "🏠 Dashboard", "callback_data": "admin:dashboard"}],
        ]},
    )
    return {"ok": True, "action": "defaultmessage_info_sent"}


async def handle_custom_messages_menu(
    client_bot_id: int,
    chat_id: int,
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Displays the custom messages management menu."""
    repo = ClientBotSettingsRepository(session)
    settings = await _get_or_create_settings(repo, client_bot_id)

    start_status = "✅ Custom" if settings.start_message else "Default"
    default_status = "✅ Custom" if settings.default_message else "Default"

    await telegram_client.send_message(
        chat_id=chat_id,
        text=(
            f"💬 <b>Custom Messages Configuration</b>\n\n"
            f"• <b>Start Message:</b> {start_status}\n"
            f"• <b>Default Reply Message:</b> {default_status}\n\n"
            f"Select an option below to customize:"
        ),
        reply_markup={"inline_keyboard": [
            [{"text": "💬 Custom Start Message", "callback_data": "admin:startmessage"}],
            [{"text": "🔁 Custom Default Reply", "callback_data": "admin:defaultmessage"}],
            [{"text": "🏠 Dashboard", "callback_data": "admin:dashboard"}],
        ]},
    )
    return {"ok": True, "action": "custom_messages_menu_sent"}


async def handle_custom_messages_callback(
    client_bot_id: int,
    telegram_user_id: int,
    chat_id: int,
    callback_data: str,
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Handles custom messages inline callbacks."""
    repo = ClientBotSettingsRepository(session)
    settings = await _get_or_create_settings(repo, client_bot_id)

    if callback_data == "admin:messages":
        return await handle_custom_messages_menu(client_bot_id, chat_id, telegram_client, session)

    if callback_data == "admin:startmessage":
        return await handle_startmessage_command(client_bot_id, telegram_user_id, chat_id, "/startmessage", telegram_client, session)

    if callback_data == "admin:startmessage:set":
        await set_messages_state(client_bot_id, telegram_user_id, WAITING_FOR_START_MESSAGE)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=(
                "💬 <b>Enter New Start Message</b>\n\n"
                "Please reply with the welcome text for new viewers.\n\n"
                "<i>Send /cancel to abort.</i>"
            ),
        )
        return {"ok": True, "action": "startmessage_set_prompt_sent"}

    if callback_data == "admin:startmessage:reset":
        settings.start_message = None
        await session.flush()
        await telegram_client.send_message(
            chat_id=chat_id,
            text="🔄 Start message reset to default system message.",
        )
        return await handle_startmessage_command(client_bot_id, telegram_user_id, chat_id, "/startmessage", telegram_client, session)

    if callback_data == "admin:defaultmessage":
        return await handle_defaultmessage_command(client_bot_id, telegram_user_id, chat_id, "/defaultmessage", telegram_client, session)

    if callback_data == "admin:defaultmessage:set":
        await set_messages_state(client_bot_id, telegram_user_id, WAITING_FOR_DEFAULT_MESSAGE)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=(
                "🔁 <b>Enter New Default Reply Message</b>\n\n"
                "Please reply with the fallback text for unrecognized messages.\n\n"
                "<i>Send /cancel to abort.</i>"
            ),
        )
        return {"ok": True, "action": "defaultmessage_set_prompt_sent"}

    if callback_data == "admin:defaultmessage:reset":
        settings.default_message = None
        await session.flush()
        await telegram_client.send_message(
            chat_id=chat_id,
            text="🔄 Default reply message reset to default system message.",
        )
        return await handle_defaultmessage_command(client_bot_id, telegram_user_id, chat_id, "/defaultmessage", telegram_client, session)

    return {"ok": True, "action": "messages_noop"}
