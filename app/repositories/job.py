"""Background Job Repository with Atomic Claiming and Recovery Queries."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func, select, update
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

    async def get_by_deduplication_key(self, key: str) -> Optional[BackgroundJob]:
        stmt = select(BackgroundJob).where(BackgroundJob.deduplication_key == key).limit(1)
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
        resource_type: Optional[str] = None,
        resource_id: Optional[int] = None,
        queue_name: str = "default",
        priority: int = 0,
        max_attempts: int = 3,
        deduplication_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
        parent_job_id: Optional[int] = None,
    ) -> BackgroundJob:
        now = utc_now()
        job = BackgroundJob(
            job_type=job_type,
            client_id=client_id,
            client_bot_id=client_bot_id,
            video_id=video_id,
            broadcast_id=broadcast_id,
            resource_type=resource_type,
            resource_id=resource_id,
            queue_name=queue_name,
            priority=priority,
            max_attempts=max_attempts,
            payload=payload,
            status=JobStatus.PENDING,
            scheduled_at=now,
            available_at=now,
            deduplication_key=deduplication_key,
            correlation_id=correlation_id,
            parent_job_id=parent_job_id,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def create_video_processing_job(
        self,
        video_id: int,
        client_bot_id: int,
        client_id: Optional[int] = None,
        thumbnail_file_id: Optional[str] = None,
        queue_name: str = "video_processing",
        priority: int = 60,
    ) -> BackgroundJob:
        """Creates a PENDING background job for video processing pipeline."""
        payload = {
            "video_id": video_id,
            "client_bot_id": client_bot_id,
        }
        if thumbnail_file_id:
            payload["thumbnail_file_id"] = thumbnail_file_id

        return await self.create_job(
            job_type=JobType.VIDEO_PROCESS,
            payload=payload,
            client_id=client_id,
            client_bot_id=client_bot_id,
            video_id=video_id,
            resource_type="video",
            resource_id=video_id,
            queue_name=queue_name,
            priority=priority,
            deduplication_key=f"video-process:{video_id}",
        )

    async def create_broadcast_job(
        self,
        broadcast_id: int,
        video_id: int,
        client_bot_id: int,
        client_id: Optional[int] = None,
        queue_name: str = "broadcast_live",
        priority: int = 80,
    ) -> BackgroundJob:
        """Creates a PENDING background job for broadcast dissemination."""
        payload = {
            "broadcast_id": broadcast_id,
            "video_id": video_id,
            "client_bot_id": client_bot_id,
        }
        return await self.create_job(
            job_type=JobType.BROADCAST,
            payload=payload,
            client_id=client_id,
            client_bot_id=client_bot_id,
            video_id=video_id,
            broadcast_id=broadcast_id,
            resource_type="broadcast",
            resource_id=broadcast_id,
            queue_name=queue_name,
            priority=priority,
            deduplication_key=f"live-broadcast:{broadcast_id}",
        )

    async def get_pending_jobs(
        self,
        job_type: Optional[JobType] = None,
        limit: int = 10,
    ) -> List[BackgroundJob]:
        """Fetches pending or retrying jobs ready for execution (available_at <= now)."""
        now = utc_now()
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RETRYING]),
                BackgroundJob.available_at <= now,
            )
        )
        if job_type is not None:
            stmt = stmt.where(BackgroundJob.job_type == job_type)
        stmt = stmt.order_by(BackgroundJob.priority.desc(), BackgroundJob.available_at.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def claim_pending_jobs(
        self,
        limit: int = 10,
        job_type: Optional[JobType] = None,
    ) -> List[BackgroundJob]:
        """Atomically claims executable pending/retrying jobs and transitions them to QUEUED."""
        now = utc_now()
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RETRYING]),
                BackgroundJob.available_at <= now,
            )
        )
        if job_type is not None:
            stmt = stmt.where(BackgroundJob.job_type == job_type)

        stmt = stmt.order_by(BackgroundJob.priority.desc(), BackgroundJob.available_at.asc()).limit(limit)
        result = await self.session.execute(stmt)
        jobs = list(result.scalars().all())

        for job in jobs:
            job.status = JobStatus.QUEUED
            job.queued_at = now
        await self.session.flush()
        return jobs

    async def get_active_for_video(self, video_id: int) -> Optional[BackgroundJob]:
        """Gets active background job (PENDING, QUEUED, RUNNING, RETRYING) for a video."""
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.video_id == video_id,
                BackgroundJob.job_type == JobType.VIDEO_PROCESS,
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRYING]),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_for_broadcast(self, broadcast_id: int) -> Optional[BackgroundJob]:
        """Gets active background job for a broadcast."""
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.broadcast_id == broadcast_id,
                BackgroundJob.job_type.in_([JobType.BROADCAST, JobType.LIVE_BROADCAST]),
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRYING]),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def has_active_catchup_job(self, client_bot_id: int, viewer_id: int) -> bool:
        """Checks if a pending or running catch-up job exists for the given viewer."""
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.client_bot_id == client_bot_id,
                BackgroundJob.job_type.in_([JobType.CATCHUP, JobType.CATCHUP_BATCH]),
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRYING]),
            )
        )
        result = await self.session.execute(stmt)
        for job in result.scalars().all():
            if job.payload and job.payload.get("viewer_id") == viewer_id:
                return True
        return False

    async def mark_queued(self, job_id: int) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.status = JobStatus.QUEUED
            job.queued_at = utc_now()
            await self.session.flush()
        return job

    async def mark_running(self, job_id: int) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.status = JobStatus.RUNNING
            job.started_at = utc_now()
            job.last_attempt_at = utc_now()
            job.last_heartbeat_at = utc_now()
            job.attempt_count += 1
            await self.session.flush()
        return job

    async def update_heartbeat(self, job_id: int) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job and job.status == JobStatus.RUNNING:
            job.last_heartbeat_at = utc_now()
            await self.session.flush()
        return job

    async def mark_completed(self, job_id: int) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = utc_now()
            job.last_error_code = None
            job.last_error_message = None
            await self.session.flush()
        return job

    async def mark_retrying(
        self,
        job_id: int,
        available_at: datetime,
        error_code: str,
        error_message: str,
    ) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.status = JobStatus.RETRYING
            job.available_at = available_at
            job.last_error_code = error_code
            job.last_error_message = error_message
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
            job.status = JobStatus.FAILED
            job.completed_at = utc_now()
            await self.session.flush()
        return job

    async def mark_paused(self, job_id: int, reason: str = "") -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.status = JobStatus.PAUSED
            if reason:
                job.last_error_message = reason
            await self.session.flush()
        return job

    async def mark_stale(self, job_id: int) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.status = JobStatus.STALE
            await self.session.flush()
        return job

    async def retry_job(self, job_id: int) -> Tuple[bool, str, Optional[BackgroundJob]]:
        job = await self.get_by_id(job_id)
        if not job:
            return False, "Job not found", None

        if job.status == JobStatus.RUNNING:
            return False, "Job is currently running", job

        if job.status not in (JobStatus.FAILED, JobStatus.RETRYING, JobStatus.STALE, JobStatus.PAUSED):
            return False, f"Job cannot be retried from status {enum_val(job.status)}", job

        now = utc_now()
        job.status = JobStatus.PENDING
        job.scheduled_at = now
        job.available_at = now
        job.started_at = None
        job.completed_at = None
        await self.session.flush()
        return True, "Retry queued successfully", job

    async def get_stale_running_jobs(
        self,
        threshold_seconds: int = 300,
        job_type: Optional[JobType] = None,
    ) -> List[BackgroundJob]:
        """Finds RUNNING jobs where heartbeat or started_at is older than threshold."""
        now = utc_now()
        cutoff = now - timedelta(seconds=threshold_seconds)
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.status == JobStatus.RUNNING,
                func.coalesce(BackgroundJob.last_heartbeat_at, BackgroundJob.started_at) < cutoff,
            )
        )
        if job_type is not None:
            stmt = stmt.where(BackgroundJob.job_type == job_type)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_stale_queued_jobs(
        self,
        threshold_seconds: int = 600,
    ) -> List[BackgroundJob]:
        """Finds QUEUED jobs that have waited past threshold without being claimed by a worker."""
        now = utc_now()
        cutoff = now - timedelta(seconds=threshold_seconds)
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.status == JobStatus.QUEUED,
                BackgroundJob.queued_at < cutoff,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

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
            .order_by(BackgroundJob.available_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        status: Optional[JobStatus] = None,
        job_type: Optional[JobType] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Tuple[List[BackgroundJob], int]:
        count_stmt = select(func.count(BackgroundJob.id))
        query_stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc())

        if status:
            count_stmt = count_stmt.where(BackgroundJob.status == status)
            query_stmt = query_stmt.where(BackgroundJob.status == status)
        if job_type:
            count_stmt = count_stmt.where(BackgroundJob.job_type == job_type)
            query_stmt = query_stmt.where(BackgroundJob.job_type == job_type)

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
