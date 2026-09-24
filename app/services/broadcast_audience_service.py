"""Broadcast Audience Service for snapshotting and keyset pagination of broadcast recipients."""

from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.viewer import Viewer
from app.logging_config import logger
from app.repositories.viewer import ViewerRepository


class BroadcastAudienceService:
    """Handles deterministic audience scoping and keyset pagination for broadcast delivery."""

    def __init__(self, session: AsyncSession, viewer_repo: Optional[ViewerRepository] = None):
        self.session = session
        self.viewer_repo = viewer_repo or ViewerRepository(session)

    async def capture_audience_snapshot(self, client_bot_id: int) -> Tuple[int, int]:
        """Captures stable snapshot boundary for a new broadcast run.

        Returns:
            Tuple of (total_targets, max_viewer_id).
            If no active viewers exist, returns (0, 0).
        """
        max_id = await self.viewer_repo.get_max_active_viewer_id(client_bot_id)
        if not max_id:
            logger.info("Bot id=%d has 0 active viewers for broadcast audience snapshot", client_bot_id)
            return 0, 0

        total_targets = await self.viewer_repo.count_active_viewers_up_to_id(
            client_bot_id=client_bot_id,
            max_id=max_id,
        )

        logger.info(
            "Captured audience snapshot for bot id=%d: total_targets=%d, max_viewer_id=%d",
            client_bot_id,
            total_targets,
            max_id,
        )
        return total_targets, max_id

    async def get_next_viewer_page(
        self,
        client_bot_id: int,
        cursor_id: int,
        max_id: Optional[int] = None,
        limit: int = 500,
    ) -> List[Viewer]:
        """Fetches the next chunk of viewers using keyset pagination (id > cursor_id).

        Args:
            client_bot_id: The owning Client Bot ID.
            cursor_id: The last processed viewer ID.
            max_id: The upper snapshot boundary (None for unbounded).
            limit: Page size limit.

        Returns:
            List of Viewer ORM instances ordered by ID ascending.
        """
        return await self.viewer_repo.list_active_viewers_keyset(
            client_bot_id=client_bot_id,
            cursor_id=cursor_id,
            max_id=max_id,
            limit=limit,
        )
