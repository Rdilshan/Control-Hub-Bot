"""Client Admin /broadcasts command and refresh callback handler."""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.client_bot_stats_service import ClientBotStatsService
from app.telegram.client import TelegramClient
from app.telegram.client_bot import keyboards, messages


async def handle_broadcasts_command(
    client_bot_id: int,
    chat_id: int,
    telegram_client: TelegramClient,
    session: AsyncSession,
    bypass_cache: bool = False,
    message_id: int = None,
) -> Dict[str, Any]:
    """Displays broadcast campaigns and catch-up delivery status."""
    stats_service = ClientBotStatsService(session)
    bcasts = await stats_service.get_broadcasts_summary(client_bot_id, bypass_cache=bypass_cache)
    text = messages.admin_broadcasts_summary_message(bcasts)
    markup = keyboards.admin_refresh_keyboard("admin:broadcasts:refresh")

    if message_id:
        try:
            await telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
            )
            return {"ok": True, "action": "admin_broadcasts_refreshed"}
        except Exception:
            pass

    await telegram_client.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=markup,
    )
    return {"ok": True, "action": "admin_broadcasts_sent"}
