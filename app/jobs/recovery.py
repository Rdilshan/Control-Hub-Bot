"""Job Recovery Service for Stale Jobs, Lost Broker Tasks, and Domain Reconciliation."""

import logging
from datetime import timedelta
from typing import Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import (
    BroadcastStatus,
    CatchupStatus,
    ClientBotStatus,
    JobStatus,
    JobType,
    VideoStatus,
)
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.broadcast import Broadcast
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.viewer import Viewer
from app.db.models.viewer_catchup import ViewerCatchup
from app.jobs.retry_policy import get_retry_policy_for_job_type
from app.repositories.broadcast import BroadcastRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository

logger = logging.getLogger(__name__)


class JobRecoveryService:
    """Detects and safely recovers stale, stranded, or lost background jobs and domain operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.job_repo = BackgroundJobRepository(session)
        self.video_repo = VideoRepository(session)
        self.broadcast_repo = BroadcastRepository(session)

    async def recover_stale_running_jobs(
        self,
        threshold_seconds: int = 300,
        job_type: Optional[JobType] = None,
    ) -> List[BackgroundJob]:
        """Recovers RUNNING jobs that stopped reporting heartbeats/progress."""
        stale_jobs = await self.job_repo.get_stale_running_jobs(
            threshold_seconds=threshold_seconds,
            job_type=job_type,
        )
        recovered: List[BackgroundJob] = []
        now = utc_now()

        for job in stale_jobs:
            policy = get_retry_policy_for_job_type(job.job_type)
            if job.attempt_count >= policy.max_attempts:
                job.status = JobStatus.FAILED
                job.last_error_code = "STALE_JOB_TIMEOUT"
                job.last_error_message = f"Job timed out in RUNNING status without heartbeat for >{threshold_seconds}s."
                job.completed_at = now
            else:
                delay = policy.calculate_delay(job.attempt_count)
                job.status = JobStatus.RETRYING
                job.available_at = now + timedelta(seconds=delay)
                job.last_error_code = "STALE_JOB_RECOVERED"
                job.last_error_message = f"Recovered stale running job. Next attempt in {int(delay)}s."
            recovered.append(job)

        await self.session.flush()
        return recovered

    async def recover_lost_queued_jobs(
        self,
        threshold_seconds: int = 600,
    ) -> List[BackgroundJob]:
        """Recovers jobs stuck in QUEUED status (e.g. when Redis restarted and lost memory queue)."""
        stale_queued = await self.job_repo.get_stale_queued_jobs(threshold_seconds=threshold_seconds)
        recovered: List[BackgroundJob] = []
        now = utc_now()

        for job in stale_queued:
            job.status = JobStatus.PENDING
            job.available_at = now
            job.queued_at = None
            recovered.append(job)

        await self.session.flush()
        return recovered

    async def reconcile_unprocessed_videos(self) -> List[BackgroundJob]:
        """Finds videos in RECEIVED status without an active processing job and creates one."""
        stmt = (
            select(Video)
            .where(Video.status == VideoStatus.RECEIVED)
        )
        result = await self.session.execute(stmt)
        videos = list(result.scalars().all())

        created_jobs: List[BackgroundJob] = []
        for video in videos:
            active_job = await self.job_repo.get_active_for_video(video.id)
            if not active_job:
                job = await self.job_repo.create_video_processing_job(
                    video_id=video.id,
                    client_bot_id=video.client_bot_id,
                )
                created_jobs.append(job)

        return created_jobs

    async def reconcile_missing_broadcasts(self) -> List[BackgroundJob]:
        """Finds READY videos without an active broadcast and creates a broadcast job."""
        stmt = (
            select(Video)
            .where(Video.status == VideoStatus.READY)
        )
        result = await self.session.execute(stmt)
        ready_videos = list(result.scalars().all())

        created_jobs: List[BackgroundJob] = []
        for video in ready_videos:
            broadcast = await self.broadcast_repo.get_by_video_id(video.id)
            if not broadcast:
                # Create broadcast domain model and job
                new_broadcast = await self.broadcast_repo.create_broadcast(
                    video_id=video.id,
                    client_bot_id=video.client_bot_id,
                    total_targets=0,
                )
                job = await self.job_repo.create_broadcast_job(
                    broadcast_id=new_broadcast.id,
                    video_id=video.id,
                    client_bot_id=video.client_bot_id,
                )
                created_jobs.append(job)
            elif broadcast.status in (BroadcastStatus.PENDING, BroadcastStatus.QUEUED):
                active_job = await self.job_repo.get_active_for_broadcast(broadcast.id)
                if not active_job:
                    job = await self.job_repo.create_broadcast_job(
                        broadcast_id=broadcast.id,
                        video_id=video.id,
                        client_bot_id=video.client_bot_id,
                    )
                    created_jobs.append(job)

        return created_jobs

    async def reconcile_stalled_catchups(self) -> List[BackgroundJob]:
        """Finds active viewer catchup states that lack a running/pending background job and re-queues them."""
        stmt = select(ViewerCatchup).where(
            ViewerCatchup.status.in_([CatchupStatus.PENDING, CatchupStatus.RUNNING, CatchupStatus.PAUSED])
        )
        result = await self.session.execute(stmt)
        catchups = list(result.scalars().all())

        requeued_jobs: List[BackgroundJob] = []
        for catchup in catchups:
            has_job = await self.job_repo.has_active_catchup_job(catchup.client_bot_id, catchup.viewer_id)
            if not has_job:
                # Reset to PENDING if stuck in RUNNING without job
                if catchup.status == CatchupStatus.RUNNING:
                    catchup.status = CatchupStatus.PENDING

                job = await self.job_repo.create_job(
                    job_type=JobType.CATCHUP,
                    payload={"viewer_id": catchup.viewer_id, "client_bot_id": catchup.client_bot_id},
                    client_bot_id=catchup.client_bot_id,
                    queue_name="catchup",
                )
                requeued_jobs.append(job)
                logger.info("Reconciled and queued missing CATCHUP job id=%d for viewer id=%d", job.id, catchup.viewer_id)

        return requeued_jobs

