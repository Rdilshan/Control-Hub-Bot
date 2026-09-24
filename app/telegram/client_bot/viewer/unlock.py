"""Viewer unlock deep-link handler."""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.client_bot import ClientBot
from app.services.viewer_unlock_service import ViewerUnlockService
from app.telegram.client import TelegramClient


async def handle_viewer_unlock_command(
    client_bot: ClientBot,
    telegram_user_id: int,
    chat_id: int | str,
    payload: str,
    actor_data: Dict[str, Any],
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Processes incoming /start unlock_<video_public_id> commands."""
    service = ViewerUnlockService(session)
    return await service.handle_unlock_request(
        client_bot=client_bot,
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        payload=payload,
        actor_data=actor_data,
        telegram_client=telegram_client,
    )
