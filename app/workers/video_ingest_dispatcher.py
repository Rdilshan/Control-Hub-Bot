"""Video Ingest Dispatcher and Job Recovery Worker."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import JobStatus, JobType, ProcessingStatus, VideoStatus
from app.db.models.background_job import BackgroundJob
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.logging_config import get_logger
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository

logger = get_logger(__name__)


class VideoIngestDispatcher:
    """Dispatches pending video intake processing jobs and recovers orphan records."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.job_repo = BackgroundJobRepository(session)
        self.video_repo = VideoRepository(session)

    async def get_pending_video_jobs(self, limit: int = 50) -> List[BackgroundJob]:
        """Fetches pending VIDEO_PROCESS background jobs ready for execution."""
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.job_type == JobType.VIDEO_PROCESS,
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RETRYING]),
            )
            .order_by(BackgroundJob.scheduled_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def recover_unprocessed_videos(self) -> int:
        """Finds videos in RECEIVED/PENDING status without an active background job and recovers them."""
        # Query videos with RECEIVED status
        stmt = (
            select(Video)
            .join(VideoProcessing, Video.id == VideoProcessing.video_id)
            .where(
                Video.status == VideoStatus.RECEIVED,
                VideoProcessing.status == ProcessingStatus.PENDING,
            )
        )
        result = await self.session.execute(stmt)
        videos = result.scalars().all()
        recovered_count = 0

        for video in videos:
            active_job = await self.job_repo.get_active_for_video(video.id)
            if not active_job:
                logger.info(f"Recovering orphan pending video #{video.id} by creating background job")
                await self.job_repo.create_video_processing_job(
                    video_id=video.id,
                    client_bot_id=video.client_bot_id,
                    thumbnail_file_id=video.source_thumbnail_file_id,
                )
                recovered_count += 1

        if recovered_count > 0:
            await self.session.commit()
            logger.info(f"Recovered {recovered_count} orphan video processing jobs")

        return recovered_count
