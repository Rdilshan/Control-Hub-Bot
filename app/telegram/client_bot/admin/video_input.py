"""Client Admin video intake handler for incoming media."""

from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.client_bot import ClientBot
from app.services.video_creation_service import VideoCreationService
from app.telegram.client import TelegramClient


async def handle_video_input(
    client_bot: ClientBot,
    telegram_user_id: int,
    chat_id: int,
    admin_id: Optional[int],
    actor_data: Dict[str, Any],
    telegram_client: TelegramClient,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Handles incoming video submission during an active creation session."""
    service = VideoCreationService(session)
    return await service.process_video_intake(
        client_bot=client_bot,
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        admin_id=admin_id,
        actor_data=actor_data,
        telegram_client=telegram_client,
    )
