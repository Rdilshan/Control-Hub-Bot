"""Client Admin /createvideo session starter and cancellation handler."""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.client_bot import ClientBot
from app.services.video_creation_service import VideoCreationService
from app.telegram.client import TelegramClient


async def handle_createvideo_command(
    client_bot: ClientBot,
    telegram_user_id: int,
    chat_id: int,
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Handles the /createvideo entrypoint for client administrators."""
    service = VideoCreationService(session)
    return await service.start_create_video_session(
        client_bot=client_bot,
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        telegram_client=telegram_client,
    )


async def handle_cancel_command(
    client_bot_id: int,
    telegram_user_id: int,
    chat_id: int,
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Handles the /cancel command when exiting a creation session."""
    service = VideoCreationService(session)
    return await service.cancel_create_video_session(
        client_bot_id=client_bot_id,
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        telegram_client=telegram_client,
    )
