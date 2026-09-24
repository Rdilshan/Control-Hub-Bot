"""Video Processing Worker for executing VIDEO_PROCESS background jobs."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import JobStatus, JobType
from app.db.models.background_job import BackgroundJob
from app.logging_config import logger
from app.repositories.job import BackgroundJobRepository
from app.services.video_processing_service import VideoProcessingService


class VideoProcessingWorker:
    """Worker for executing queued video processing tasks."""

    def __init__(self, session: AsyncSession, video_processing_service: Optional[VideoProcessingService] = None):
        self.session = session
        self.job_repo = BackgroundJobRepository(session)
        self.service = video_processing_service or VideoProcessingService(session)

    async def get_pending_jobs(self, limit: int = 10) -> List[BackgroundJob]:
        """Fetches pending VIDEO_PROCESS jobs ready to run."""
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

    async def process_job(self, job_id: int) -> Dict[str, Any]:
        """Executes a single video processing background job."""
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            logger.warning("Job id=%d not found", job_id)
            return {"ok": False, "error": "job_not_found"}

        video_id = job.video_id or (job.payload or {}).get("video_id")
        if not video_id:
            logger.error("Job id=%d missing video_id in payload", job_id)
            await self.job_repo.mark_failed(job_id, "MISSING_VIDEO_ID", "No video_id specified in job payload")
            await self.session.commit()
            return {"ok": False, "error": "MISSING_VIDEO_ID"}

        await self.job_repo.mark_running(job_id)
        await self.session.commit()

        try:
            result = await self.service.process_video(video_id)
            if result.get("ok"):
                await self.job_repo.mark_completed(job_id)
            else:
                error_code = result.get("error", "PROCESSING_FAILED")
                error_message = result.get("message", "Processing failed")
                await self.job_repo.mark_failed(job_id, error_code, error_message)
            await self.session.commit()
            return result
        except Exception as exc:
            logger.exception("Unexpected error executing job id=%d: %s", job_id, exc)
            await self.job_repo.mark_failed(job_id, "UNEXPECTED_ERROR", str(exc))
            await self.session.commit()
            return {"ok": False, "error": "UNEXPECTED_ERROR", "message": str(exc)}
