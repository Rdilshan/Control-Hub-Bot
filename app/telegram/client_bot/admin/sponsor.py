"""Client Admin /sponsor configuration handler."""

import asyncio
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sponsor_config import SponsorConfig
from app.exceptions import ValidationError
from app.logging_config import get_logger
from app.redis.client import get_redis
from app.services.client_bot_sponsor_service import ClientBotSponsorService
from app.telegram.client import TelegramClient

logger = get_logger(__name__)

SPONSOR_STATE_PREFIX = "controlhub:clientbot:sponsor_state:"
SPONSOR_STATE_TTL = 1800  # 30 minutes
WAITING_FOR_SPONSOR_URL = "WAITING_FOR_SPONSOR_URL"

_in_memory_sponsor_state: Dict[str, str] = {}
_sponsor_lock = asyncio.Lock()


async def get_sponsor_state(client_bot_id: int, telegram_user_id: int) -> Optional[str]:
    key = f"{SPONSOR_STATE_PREFIX}{client_bot_id}:{telegram_user_id}"
    try:
        redis = get_redis()
        return await redis.get(key)
    except Exception:
        async with _sponsor_lock:
            return _in_memory_sponsor_state.get(key)


async def set_sponsor_state(client_bot_id: int, telegram_user_id: int, state: str) -> None:
    key = f"{SPONSOR_STATE_PREFIX}{client_bot_id}:{telegram_user_id}"
    try:
        redis = get_redis()
        await redis.set(key, state, ex=SPONSOR_STATE_TTL)
    except Exception:
        async with _sponsor_lock:
            _in_memory_sponsor_state[key] = state


async def clear_sponsor_state(client_bot_id: int, telegram_user_id: int) -> None:
    key = f"{SPONSOR_STATE_PREFIX}{client_bot_id}:{telegram_user_id}"
    try:
        redis = get_redis()
        await redis.delete(key)
    except Exception:
        async with _sponsor_lock:
            _in_memory_sponsor_state.pop(key, None)


def sponsor_keyboard(sponsor: Optional[SponsorConfig]) -> Dict[str, Any]:
    buttons = []
    first_row = [
        {"text": "✏️ Set / Change Link", "callback_data": "admin:sponsor:set"}
    ]
    if sponsor and sponsor.sponsor_url:
        if sponsor.is_enabled:
            first_row.append({"text": "⏸ Disable", "callback_data": "admin:sponsor:disable"})
        else:
            first_row.append({"text": "▶️ Enable", "callback_data": "admin:sponsor:enable"})
    buttons.append(first_row)
    buttons.append([
        {"text": "🎬 Create Video", "callback_data": "admin:createvideo"},
        {"text": "🏠 Dashboard", "callback_data": "admin:dashboard"},
    ])
    return {"inline_keyboard": buttons}


def format_sponsor_text(sponsor: Optional[SponsorConfig]) -> str:
    if not sponsor or not sponsor.sponsor_url:
        status_text = "⚠️ <b>Not Configured</b>"
        url_text = "<i>None</i>"
    else:
        status_text = "✅ <b>Enabled</b>" if sponsor.is_enabled else "⏸ <b>Disabled</b>"
        url_text = f"<code>{sponsor.sponsor_url}</code>"

    return (
        f"🔓 <b>Sponsor / Monetization Configuration</b>\n\n"
        f"<b>Status:</b> {status_text}\n"
        f"<b>Direct Link / Offer URL:</b>\n{url_text}\n\n"
        f"<i>You can send your monetization direct link (e.g. Monetag, Adsterra, or CPA link) "
        f"or use:</i>\n"
        f"<code>/sponsor &lt;your-url&gt;</code>"
    )


async def handle_sponsor_command(
    client_bot_id: int,
    telegram_user_id: int,
    chat_id: int,
    text: str,
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Handles /sponsor command with or without argument."""
    service = ClientBotSponsorService(session)
    parts = text.strip().split(maxsplit=1)
    
    # If URL is passed directly with command: e.g. /sponsor https://...
    if len(parts) > 1 and parts[1].strip():
        url_input = parts[1].strip()
        return await apply_sponsor_url(
            client_bot_id=client_bot_id,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            url=url_input,
            telegram_client=telegram_client,
            session=session,
        )

    sponsor = await service.get_sponsor(client_bot_id)
    await telegram_client.send_message(
        chat_id=chat_id,
        text=format_sponsor_text(sponsor),
        reply_markup=sponsor_keyboard(sponsor),
    )
    return {"ok": True, "action": "sponsor_dashboard_sent"}


async def apply_sponsor_url(
    client_bot_id: int,
    telegram_user_id: int,
    chat_id: int,
    url: str,
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Validates and persists the sponsor URL."""
    service = ClientBotSponsorService(session)
    try:
        sponsor = await service.set_sponsor_url(client_bot_id, url, enable=True)
        await clear_sponsor_state(client_bot_id, telegram_user_id)
        
        await telegram_client.send_message(
            chat_id=chat_id,
            text=(
                f"✅ <b>Sponsor URL Saved & Enabled!</b>\n\n"
                f"<b>Direct Link:</b>\n<code>{sponsor.sponsor_url}</code>\n\n"
                f"You can now create videos with <b>/createvideo</b>."
            ),
            reply_markup=sponsor_keyboard(sponsor),
        )
        return {"ok": True, "action": "sponsor_url_saved"}
    except ValidationError as e:
        await telegram_client.send_message(
            chat_id=chat_id,
            text=f"⚠️ <b>Invalid Sponsor URL:</b> {str(e)}\n\nPlease provide a valid URL starting with <code>https://</code> or <code>http://</code>.",
        )
        return {"ok": False, "error": str(e)}


async def handle_sponsor_callback(
    client_bot_id: int,
    telegram_user_id: int,
    chat_id: int,
    callback_data: str,
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Handles sponsor inline keyboard actions."""
    service = ClientBotSponsorService(session)

    if callback_data == "admin:sponsor:set":
        await set_sponsor_state(client_bot_id, telegram_user_id, WAITING_FOR_SPONSOR_URL)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=(
                "🔗 <b>Enter Sponsor Direct Link</b>\n\n"
                "Please reply with your monetization direct link (e.g. <code>https://your-ad-network.com/direct-link</code>).\n\n"
                "<i>Send /cancel to abort.</i>"
            ),
        )
        return {"ok": True, "action": "sponsor_set_prompt_sent"}

    if callback_data == "admin:sponsor:enable":
        try:
            sponsor = await service.enable_sponsor(client_bot_id)
            await telegram_client.send_message(
                chat_id=chat_id,
                text="✅ Sponsor enabled successfully.",
                reply_markup=sponsor_keyboard(sponsor),
            )
            return {"ok": True, "action": "sponsor_enabled"}
        except ValidationError as e:
            await telegram_client.send_message(
                chat_id=chat_id,
                text=f"⚠️ {str(e)}",
            )
            return {"ok": False, "error": str(e)}

    if callback_data == "admin:sponsor:disable":
        sponsor = await service.disable_sponsor(client_bot_id)
        await telegram_client.send_message(
            chat_id=chat_id,
            text="⏸ Sponsor disabled. (Videos cannot be processed without an active sponsor)",
            reply_markup=sponsor_keyboard(sponsor),
        )
        return {"ok": True, "action": "sponsor_disabled"}

    # Default: show sponsor info
    sponsor = await service.get_sponsor(client_bot_id)
    await telegram_client.send_message(
        chat_id=chat_id,
        text=format_sponsor_text(sponsor),
        reply_markup=sponsor_keyboard(sponsor),
    )
    return {"ok": True, "action": "sponsor_info_sent"}
