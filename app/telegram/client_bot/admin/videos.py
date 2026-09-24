"""Client Admin /videos library command handler."""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.video import VideoRepository
from app.telegram.client import TelegramClient
from app.telegram.client_bot import messages


async def handle_videos_command(
    client_bot_id: int,
    chat_id: int,
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Displays recent videos published or received by the bot."""
    video_repo = VideoRepository(session)
    videos = await video_repo.list_by_bot(client_bot_id=client_bot_id, limit=10)
    text = messages.admin_videos_list_message(videos)
    await telegram_client.send_message(chat_id=chat_id, text=text)
    return {"ok": True, "action": "admin_videos_list", "count": len(videos)}
