"""Client Admin /processing queue and stage breakdown command handler."""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.video import VideoRepository
from app.services.client_bot_stats_service import ClientBotStatsService
from app.telegram.client import TelegramClient
from app.telegram.client_bot import keyboards, messages


async def handle_processing_command(
    client_bot_id: int,
    chat_id: int,
    telegram_client: TelegramClient,
    session: AsyncSession,
    bypass_cache: bool = False,
    message_id: int = None,
) -> Dict[str, Any]:
    """Displays videos currently in processing queue and detailed stage breakdown."""
    stats_service = ClientBotStatsService(session)
    proc_stats = await stats_service.get_processing_summary(client_bot_id, bypass_cache=bypass_cache)
    
    video_repo = VideoRepository(session)
    active_videos = await video_repo.list_processing_by_bot(client_bot_id=client_bot_id, limit=5)
    
    summary_text = messages.admin_processing_summary_message(proc_stats)
    list_text = messages.admin_processing_list_message(active_videos)
    full_text = f"{summary_text}\n\n{list_text}"
    markup = keyboards.admin_refresh_keyboard("admin:processing:refresh")

    if message_id:
        try:
            await telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=full_text,
                reply_markup=markup,
            )
            return {"ok": True, "action": "admin_processing_refreshed"}
        except Exception:
            pass

    await telegram_client.send_message(
        chat_id=chat_id,
        text=full_text,
        reply_markup=markup,
    )
    return {"ok": True, "action": "admin_processing_list", "count": len(active_videos)}
