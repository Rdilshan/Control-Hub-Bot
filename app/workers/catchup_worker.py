"""Catch-Up Worker for executing CATCHUP background jobs."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import JobStatus, JobType
from app.db.models.background_job import BackgroundJob
from app.logging_config import logger
from app.repositories.job import BackgroundJobRepository
from app.services.catchup_service import CatchupService


class CatchupWorker:
    """Worker for executing automated catch-up batch jobs."""

    def __init__(
        self,
        session: AsyncSession,
        catchup_service: Optional[CatchupService] = None,
    ):
        self.session = session
        self.job_repo = BackgroundJobRepository(session)
        self.service = catchup_service or CatchupService(session)

    async def get_pending_jobs(self, limit: int = 10) -> List[BackgroundJob]:
        """Fetches pending CATCHUP jobs ready to run."""
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.job_type == JobType.CATCHUP,
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RETRYING]),
            )
            .order_by(BackgroundJob.scheduled_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def process_job(self, job_id: int) -> Dict[str, Any]:
        """Executes a single catch-up background job."""
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            logger.warning("Catch-up job id=%d not found", job_id)
            return {"ok": False, "error": "job_not_found"}

        viewer_id = (job.payload or {}).get("viewer_id")
        if not viewer_id:
            logger.error("Job id=%d missing viewer_id in payload", job_id)
            await self.job_repo.mark_failed(job_id, "MISSING_VIEWER_ID", "No viewer_id in job payload")
            await self.session.commit()
            return {"ok": False, "error": "MISSING_VIEWER_ID"}

        await self.job_repo.mark_running(job_id)
        await self.session.commit()

        try:
            result = await self.service.process_viewer_catchup_batch(viewer_id)
            if result.get("ok"):
                await self.job_repo.mark_completed(job_id)
            else:
                error_code = result.get("error", "CATCHUP_FAILED")
                error_message = result.get("message", "Catch-up execution failed")
                await self.job_repo.mark_failed(job_id, error_code, error_message)
            await self.session.commit()
            return result
        except Exception as exc:
            logger.exception("Unexpected error executing catchup job id=%d: %s", job_id, exc)
            await self.session.rollback()
            try:
                await self.job_repo.mark_failed(job_id, "UNEXPECTED_ERROR", str(exc))
                await self.session.commit()
            except Exception as mark_err:
                logger.error("Failed to mark catchup job %d as failed: %s", job_id, mark_err)
            return {"ok": False, "error": "UNEXPECTED_ERROR", "message": str(exc)}
