"""Client Admin /users command and refresh callback handler."""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.client_bot_stats_service import ClientBotStatsService
from app.telegram.client import TelegramClient
from app.telegram.client_bot import keyboards, messages


async def handle_users_command(
    client_bot_id: int,
    chat_id: int,
    telegram_client: TelegramClient,
    session: AsyncSession,
    bypass_cache: bool = False,
    message_id: int = None,
) -> Dict[str, Any]:
    """Displays audience growth and active/blocked user metrics."""
    stats_service = ClientBotStatsService(session)
    users = await stats_service.get_users_summary(client_bot_id, bypass_cache=bypass_cache)
    text = messages.admin_users_message(users)
    markup = keyboards.admin_refresh_keyboard("admin:users:refresh")

    if message_id:
        try:
            await telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
            )
            return {"ok": True, "action": "admin_users_refreshed"}
        except Exception:
            pass

    await telegram_client.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=markup,
    )
    return {"ok": True, "action": "admin_users_sent"}
