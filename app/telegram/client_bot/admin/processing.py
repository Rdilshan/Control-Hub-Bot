"""Client Admin /processing queue command handler."""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.video import VideoRepository
from app.telegram.client import TelegramClient
from app.telegram.client_bot import messages


async def handle_processing_command(
    client_bot_id: int,
    chat_id: int,
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Displays videos currently in the intake / conversion processing queue."""
    video_repo = VideoRepository(session)
    processing_videos = await video_repo.list_processing_by_bot(client_bot_id=client_bot_id, limit=10)
    text = messages.admin_processing_list_message(processing_videos)
    await telegram_client.send_message(chat_id=chat_id, text=text)
    return {"ok": True, "action": "admin_processing_list", "count": len(processing_videos)}
