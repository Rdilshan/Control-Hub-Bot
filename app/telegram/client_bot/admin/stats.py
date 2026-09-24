"""Client Admin /stats command and refresh callback handler."""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.client_bot_stats_service import ClientBotStatsService
from app.telegram.client import TelegramClient
from app.telegram.client_bot import keyboards, messages


async def handle_stats_command(
    client_bot_id: int,
    chat_id: int,
    telegram_client: TelegramClient,
    session: AsyncSession,
    bypass_cache: bool = False,
    message_id: int = None,
) -> Dict[str, Any]:
    """Displays or refreshes aggregate bot performance analytics."""
    stats_service = ClientBotStatsService(session)
    summary = await stats_service.get_stats_summary(client_bot_id, bypass_cache=bypass_cache)
    text = messages.admin_stats_message(summary)
    markup = keyboards.admin_refresh_keyboard("admin:stats:refresh")

    if message_id:
        try:
            await telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
            )
            return {"ok": True, "action": "admin_stats_refreshed"}
        except Exception:
            pass

    await telegram_client.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=markup,
    )
    return {"ok": True, "action": "admin_stats_sent"}
