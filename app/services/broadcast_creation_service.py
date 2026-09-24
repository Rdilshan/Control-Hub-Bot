"""Broadcast creation service for queuing LIVE broadcasts after video processing."""

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import ViewerStatus
from app.db.models.broadcast import Broadcast
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.logging_config import logger
from app.repositories.broadcast import BroadcastRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.viewer import ViewerRepository


class BroadcastCreationService:
    """Handles idempotent creation and background scheduling of video broadcasts."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.broadcast_repo = BroadcastRepository(session)
        self.viewer_repo = ViewerRepository(session)
        self.job_repo = BackgroundJobRepository(session)

    async def create_live_broadcast(
        self,
        video: Video,
        client_bot: ClientBot,
    ) -> Broadcast:
        """Creates a LIVE broadcast and queues its background dispatch job idempotently.

        Args:
            video: The READY video to broadcast.
            client_bot: The ClientBot owning the video.

        Returns:
            The created or existing Broadcast instance.
        """
        # 1. Check if a broadcast already exists for this video (Idempotency)
        existing_broadcast = await self.broadcast_repo.get_by_video_id(video.id)
        if existing_broadcast:
            logger.info(
                "Broadcast already exists for video_id=%d (broadcast_id=%d). Checking job...",
                video.id,
                existing_broadcast.id,
            )
            existing_job = await self.job_repo.get_active_for_broadcast(existing_broadcast.id)
            if not existing_job:
                await self.job_repo.create_broadcast_job(
                    broadcast_id=existing_broadcast.id,
                    video_id=video.id,
                    client_bot_id=client_bot.id,
                    client_id=client_bot.client_id,
                )
            return existing_broadcast

        # 2. Count active viewers
        total_viewers = await self.viewer_repo.count_by_bot(client_bot.id, status=ViewerStatus.ACTIVE)

        # 3. Create broadcast record
        broadcast = await self.broadcast_repo.create_broadcast(
            client_bot_id=client_bot.id,
            video_id=video.id,
            total_targets=total_viewers,
            created_by_admin_id=video.created_by_admin_id,
            target_type="ALL_ACTIVE_VIEWERS",
        )

        # 4. Schedule background job
        await self.job_repo.create_broadcast_job(
            broadcast_id=broadcast.id,
            video_id=video.id,
            client_bot_id=client_bot.id,
            client_id=client_bot.client_id,
        )

        logger.info(
            "Created LIVE broadcast id=%d for video_id=%d with %d target viewers",
            broadcast.id,
            video.id,
            total_viewers,
        )
        return broadcast
