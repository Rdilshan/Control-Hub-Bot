"""Client Account Bot Summary Service for aggregate account-level reporting."""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.client_bot import ClientBotRepository


class ClientAccountBotSummaryService:
    """Provides high-level aggregate summary statistics across all bots owned by a client."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.bot_repo = ClientBotRepository(session)

    async def get_account_summary(self, client_id: int) -> Dict[str, Any]:
        """Calculates total, active, paused, attention-needed bots, viewers, and videos for a client account."""
        agg = await self.bot_repo.get_client_aggregate_metrics(client_id=client_id)
        return {
            "total_bots": agg.get("total", 0),
            "active_bots": agg.get("active", 0),
            "paused_bots": agg.get("paused", 0),
            "disconnected_bots": agg.get("disconnected", 0),
            "needs_attention_bots": agg.get("needs_attention", 0),
            "total_viewers": agg.get("total_viewers", 0),
            "total_videos": agg.get("total_videos", 0),
        }
