"""Background Job Repository."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import JobStatus, JobType, enum_val
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.repositories.base import BaseRepository


class BackgroundJobRepository(BaseRepository[BackgroundJob]):
    def __init__(self, session: AsyncSession):
        super().__init__(BackgroundJob, session)

    async def get_by_id(self, job_id: int) -> Optional[BackgroundJob]:
        stmt = select(BackgroundJob).where(BackgroundJob.id == job_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_job(
        self,
        job_type: JobType,
        payload: Dict[str, Any],
        client_id: Optional[int] = None,
        client_bot_id: Optional[int] = None,
        video_id: Optional[int] = None,
        broadcast_id: Optional[int] = None,
        queue_name: str = "default",
        max_attempts: int = 3,
    ) -> BackgroundJob:
        job = BackgroundJob(
            job_type=job_type,
            client_id=client_id,
            client_bot_id=client_bot_id,
            video_id=video_id,
            broadcast_id=broadcast_id,
            queue_name=queue_name,
            max_attempts=max_attempts,
            payload=payload,
            status=JobStatus.PENDING,
            scheduled_at=utc_now(),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def mark_running(self, job_id: int) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.status = JobStatus.RUNNING
            job.started_at = utc_now()
            job.attempt_count += 1
            await self.session.flush()
        return job

    async def mark_completed(self, job_id: int) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = utc_now()
            await self.session.flush()
        return job

    async def mark_failed(
        self,
        job_id: int,
        error_code: str,
        error_message: str,
    ) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.last_error_code = error_code
            job.last_error_message = error_message
            if job.attempt_count < job.max_attempts:
                job.status = JobStatus.RETRYING
            else:
                job.status = JobStatus.FAILED
                job.completed_at = utc_now()
            await self.session.flush()
        return job

    async def retry_job(self, job_id: int) -> Tuple[bool, str, Optional[BackgroundJob]]:
        job = await self.get_by_id(job_id)
        if not job:
            return False, "Job not found", None

        if job.status == JobStatus.RUNNING:
            return False, "Job is currently running", job

        if job.status not in (JobStatus.FAILED, JobStatus.RETRYING):
            return False, f"Job cannot be retried from status {enum_val(job.status)}", job

        job.status = JobStatus.PENDING
        job.scheduled_at = utc_now()
        job.started_at = None
        job.completed_at = None
        await self.session.flush()
        return True, "Retry queued successfully", job

    async def count_all(self) -> int:
        stmt = select(func.count(BackgroundJob.id))
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_status(self, status: JobStatus) -> int:
        stmt = select(func.count(BackgroundJob.id)).where(BackgroundJob.status == status)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_type(self, job_type: JobType, status: Optional[JobStatus] = None) -> int:
        stmt = select(func.count(BackgroundJob.id)).where(BackgroundJob.job_type == job_type)
        if status:
            stmt = stmt.where(BackgroundJob.status == status)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_completed_since(self, since: datetime) -> int:
        stmt = select(func.count(BackgroundJob.id)).where(
            BackgroundJob.status == JobStatus.COMPLETED,
            BackgroundJob.completed_at >= since,
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_oldest_queued(self) -> Optional[BackgroundJob]:
        stmt = (
            select(BackgroundJob)
            .where(BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RETRYING]))
            .order_by(BackgroundJob.scheduled_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        status: Optional[JobStatus] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Tuple[List[BackgroundJob], int]:
        count_stmt = select(func.count(BackgroundJob.id))
        query_stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc())

        if status:
            count_stmt = count_stmt.where(BackgroundJob.status == status)
            query_stmt = query_stmt.where(BackgroundJob.status == status)

        total_res = await self.session.execute(count_stmt)
        total_count = total_res.scalar() or 0

        offset = max(0, (page - 1) * page_size)
        query_stmt = query_stmt.limit(page_size).offset(offset)
        result = await self.session.execute(query_stmt)
        items = list(result.scalars().all())

        return items, total_count

    async def list_by_bot(
        self,
        client_bot_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[BackgroundJob]:
        stmt = (
            select(BackgroundJob)
            .where(BackgroundJob.client_bot_id == client_bot_id)
            .order_by(BackgroundJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
