"""Client Bot Management Service for multi-bot listing, detail aggregation, and tenant scoping."""

from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ClientBotStatus, enum_val
from app.db.models.client_bot import ClientBot
from app.logging_config import logger
from app.repositories.client_bot import ClientBotRepository
from app.repositories.client_bot_settings import ClientBotSettingsRepository
from app.repositories.sponsor import SponsorRepository


class ClientBotManagementService:
    """Provides high-level multi-bot management queries and aggregation strictly scoped to the tenant client."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.bot_repo = ClientBotRepository(session)
        self.settings_repo = ClientBotSettingsRepository(session)
        self.sponsor_repo = SponsorRepository(session)

    async def list_client_bots(
        self,
        client_id: int,
        page: int = 1,
        page_size: int = 10,
        status: Optional[ClientBotStatus] = None,
    ) -> Tuple[List[ClientBot], int, Dict[str, int]]:
        """Retrieves paginated bots for a client along with summary status counters."""
        bots, total_count = await self.bot_repo.list_by_client_paginated(
            client_id=client_id,
            page=page,
            page_size=page_size,
            status=status,
        )
        status_counts = await self.bot_repo.count_by_client_and_status(client_id=client_id)
        return bots, total_count, status_counts

    async def get_bot_detail(
        self,
        client_id: int,
        client_bot_id: int,
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """Retrieves detailed configuration and metrics for a specific bot, enforcing client ownership."""
        bot = await self.bot_repo.get_by_id_and_client(bot_id=client_bot_id, client_id=client_id)
        if not bot:
            logger.warning(
                f"Multi-bot detail access denied: Client #{client_id} does not own Bot #{client_bot_id}"
            )
            return False, None, "Bot not found or access denied"

        settings = await self.settings_repo.get_by_bot_id(bot.id)
        sponsor = await self.sponsor_repo.get_by_bot_id(bot.id)
        metrics = await self.bot_repo.get_bot_metrics(bot.id)

        detail = {
            "id": bot.id,
            "client_id": bot.client_id,
            "telegram_bot_id": bot.telegram_bot_id,
            "username": bot.username,
            "display_name": bot.display_name,
            "public_id": bot.public_id,
            "status": enum_val(bot.status),
            "status_reason": bot.status_reason,
            "connected_at": bot.connected_at,
            "paused_at": bot.paused_at,
            "disconnected_at": bot.disconnected_at,
            "last_verified_at": bot.last_verified_at,
            "start_message": settings.start_message if settings else None,
            "default_message": settings.default_message if settings else None,
            "sponsor_enabled": sponsor.is_enabled if sponsor else False,
            "sponsor_button_text": sponsor.button_text if sponsor else None,
            "viewers_count": metrics["viewers_count"],
            "videos_count": metrics["videos_count"],
            "broadcasts_count": metrics["broadcasts_count"],
        }
        return True, detail, None

    async def get_client_bots_summary(self, client_id: int) -> Dict[str, Any]:
        """Returns aggregate summary statistics across all bots owned by a client."""
        return await self.bot_repo.get_client_aggregate_metrics(client_id=client_id)
