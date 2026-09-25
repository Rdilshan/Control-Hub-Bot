"""Manual and Automated Job Retry Service with Checkpoint Awareness and Auditing."""

from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import (
    BotEventType,
    JobStatus,
    JobType,
    ProcessingStatus,
    VideoStatus,
    enum_val,
)
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.bot_event import BotEvent
from app.repositories.broadcast import BroadcastRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository
from app.repositories.video_processing import VideoProcessingRepository


class JobRetryService:
    """Provides safe, checkpoint-aware manual and automated retry capabilities."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.job_repo = BackgroundJobRepository(session)
        self.video_repo = VideoRepository(session)
        self.video_proc_repo = VideoProcessingRepository(session)
        self.broadcast_repo = BroadcastRepository(session)

    async def can_retry(self, job: BackgroundJob) -> bool:
        """Determines if a job is in an eligible state for retry without duplicate active executions."""
        if not job or job.status in (JobStatus.RUNNING, JobStatus.QUEUED):
            return False

        # If it's for a video or broadcast, check if another active job exists
        if job.video_id and job.job_type == JobType.VIDEO_PROCESS:
            active = await self.job_repo.get_active_for_video(job.video_id)
            if active and active.id != job.id:
                return False

        return job.status in (JobStatus.FAILED, JobStatus.RETRYING, JobStatus.STALE, JobStatus.PAUSED)

    async def retry_job(
        self,
        job_id: int,
        user_id: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[BackgroundJob]]:
        """Manually retries a failed or retrying background job."""
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            return False, "Job not found", None

        if not await self.can_retry(job):
            return False, f"Job cannot be retried (current status: {enum_val(job.status)})", job

        now = utc_now()
        job.status = JobStatus.PENDING
        job.available_at = now
        job.scheduled_at = now
        job.started_at = None
        job.completed_at = None

        # Record audit event if bot is known
        if job.client_bot_id:
            event = BotEvent(
                client_bot_id=job.client_bot_id,
                event_type=BotEventType.JOB_MANUAL_RETRY,
                metadata_json={
                    "job_id": job.id,
                    "job_type": enum_val(job.job_type),
                    "initiated_by_user_id": user_id,
                },
            )
            self.session.add(event)
            await self.session.flush()

        return True, "Job queued for retry successfully", job

    async def retry_video_processing(
        self,
        video_id: int,
        client_bot_id: int,
        user_id: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[BackgroundJob]]:
        """Retries a failed video processing pipeline, preserving saved preview checkpoints."""
        video = await self.video_repo.get_by_id(video_id)
        if not video or video.client_bot_id != client_bot_id:
            return False, "Video not found", None

        # Check existing active processing job
        active_job = await self.job_repo.get_active_for_video(video_id)
        if active_job:
            return False, "Video processing is already in progress", active_job

        # Check existing processing record for checkpoints
        proc = await self.video_proc_repo.get_by_video_id(video_id)
        thumbnail_id = None
        if proc:
            thumbnail_id = getattr(proc, "thumbnail_file_id", None) or getattr(proc, "preview_file_id", None)
            if thumbnail_id:
                proc.status = ProcessingStatus.CREATING_UNLOCK_LINK
            else:
                proc.status = ProcessingStatus.PROCESSING


        # Reset video status
        video.status = VideoStatus.PROCESSING

        job = await self.job_repo.create_video_processing_job(
            video_id=video_id,
            client_bot_id=client_bot_id,
            thumbnail_file_id=thumbnail_id,
        )

        event = BotEvent(
            client_bot_id=client_bot_id,
            event_type=BotEventType.JOB_MANUAL_RETRY,
            metadata_json={
                "video_id": video_id,
                "job_id": job.id,
                "initiated_by_user_id": user_id,
            },
        )
        self.session.add(event)
        await self.session.flush()

        return True, "Video processing retry initiated", job

