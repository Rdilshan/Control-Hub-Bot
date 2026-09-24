"""Catch-Up Video Selector Service for querying eligible unseen historical READY videos."""

from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import VideoStatus
from app.db.models.video import Video
from app.logging_config import logger
from app.repositories.catchup import CatchupDeliveryRepository
from app.repositories.video import VideoRepository


class CatchupVideoSelectorService:
    """Finds and filters eligible historical READY videos for a viewer, excluding already delivered ones."""

    def __init__(
        self,
        session: AsyncSession,
        video_repo: Optional[VideoRepository] = None,
        catchup_delivery_repo: Optional[CatchupDeliveryRepository] = None,
    ):
        self.session = session
        self.video_repo = video_repo or VideoRepository(session)
        self.catchup_delivery_repo = catchup_delivery_repo or CatchupDeliveryRepository(session)

    async def get_max_ready_video_id(self, client_bot_id: int) -> Optional[int]:
        """Returns the highest video ID currently in READY status for this bot."""
        stmt = (
            select(func.max(Video.id))
            .where(
                Video.client_bot_id == client_bot_id,
                Video.status == VideoStatus.READY,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar()

    async def count_eligible_unseen_videos(
        self,
        client_bot_id: int,
        viewer_id: int,
        target_max_video_id: Optional[int] = None,
    ) -> int:
        """Counts how many READY videos up to target_max_video_id have not been delivered to the viewer."""
        delivered_ids = await self.catchup_delivery_repo.list_delivered_video_ids_for_viewer(viewer_id)

        stmt = select(func.count(Video.id)).where(
            Video.client_bot_id == client_bot_id,
            Video.status == VideoStatus.READY,
        )
        if target_max_video_id is not None:
            stmt = stmt.where(Video.id <= target_max_video_id)
        if delivered_ids:
            stmt = stmt.where(Video.id.notin_(delivered_ids))

        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_next_eligible_videos(
        self,
        client_bot_id: int,
        viewer_id: int,
        cursor_video_id: int = 0,
        target_max_video_id: Optional[int] = None,
        limit: int = 10,
    ) -> List[Video]:
        """Fetches the next chunk of eligible, unseen READY videos ordered by id ASC.

        Args:
            client_bot_id: The client bot ID.
            viewer_id: The recipient viewer ID.
            cursor_video_id: Keyset cursor (id > cursor_video_id).
            target_max_video_id: Snapshot boundary.
            limit: Maximum count of videos to return.

        Returns:
            List of Video objects.
        """
        delivered_ids = await self.catchup_delivery_repo.list_delivered_video_ids_for_viewer(viewer_id)

        stmt = (
            select(Video)
            .where(
                Video.client_bot_id == client_bot_id,
                Video.status == VideoStatus.READY,
                Video.id > cursor_video_id,
            )
        )
        if target_max_video_id is not None:
            stmt = stmt.where(Video.id <= target_max_video_id)
        if delivered_ids:
            stmt = stmt.where(Video.id.notin_(delivered_ids))

        stmt = stmt.order_by(Video.id.asc()).limit(limit)
        result = await self.session.execute(stmt)
        videos = list(result.scalars().all())

        logger.debug(
            "Found %d eligible unseen catchup videos for viewer_id=%d (cursor=%d, max_id=%s)",
            len(videos),
            viewer_id,
            cursor_video_id,
            target_max_video_id,
        )
        return videos
