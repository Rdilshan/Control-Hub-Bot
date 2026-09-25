"""Dedicated Unlockify Worker with Idempotency and Checkpoint Awareness."""

import logging
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import ErrorClassification, ProcessingStatus
from app.jobs.failure_classifier import JobFailureClassifier
from app.repositories.job import BackgroundJobRepository
from app.repositories.unlock_link import UnlockLinkRepository
from app.repositories.video_processing import VideoProcessingRepository

logger = logging.getLogger(__name__)


async def process_unlockify_link_job(
    session: AsyncSession,
    job_id: int,
    video_id: int,
    client_bot_id: int,
    sponsor_url: str,
    unlockify_client: Optional[Any] = None,
) -> bool:
    """Executes Unlockify link creation idempotently, avoiding re-calls if a valid URL already exists."""
    job_repo = BackgroundJobRepository(session)
    proc_repo = VideoProcessingRepository(session)
    link_repo = UnlockLinkRepository(session)

    job = await job_repo.mark_running(job_id)

    # 1. Check if unlock link already exists for this video
    existing_link = await link_repo.get_by_video_id(video_id)
    existing_url = getattr(existing_link, "url", None) or getattr(existing_link, "unlock_url", None) if existing_link else None
    if existing_link and existing_url:
        logger.info("Unlock URL already exists for video %s: %s. Skipping provider call.", video_id, existing_url)
        proc = await proc_repo.get_by_video_id(video_id)
        if proc:
            proc.status = ProcessingStatus.READY
        if job:
            await job_repo.mark_completed(job_id)
        return True


    # 2. Call Unlockify provider if needed
    try:
        unlock_url = ""
        if unlockify_client:
            unlock_url = await unlockify_client.create_link(sponsor_url=sponsor_url, video_id=video_id)
        else:
            unlock_url = f"https://unlockify.it/v/{video_id}"

        # Persist unlock link
        if not existing_link:
            await link_repo.create_link(
                video_id=video_id,
                client_bot_id=client_bot_id,
                unlock_url=unlock_url,
            )

        proc = await proc_repo.get_by_video_id(video_id)
        if proc:
            proc.status = ProcessingStatus.READY

        if job:
            await job_repo.mark_completed(job_id)
        return True

    except Exception as exc:
        details = JobFailureClassifier.classify(exc)
        if job:
            if details.is_retryable and job.attempt_count < job.max_attempts:
                from datetime import timedelta
                from app.core.utils import utc_now
                from app.jobs.retry_policy import get_retry_policy_for_job_type
                policy = get_retry_policy_for_job_type(job.job_type)
                delay = policy.calculate_delay(job.attempt_count, details.retry_after)
                await job_repo.mark_retrying(
                    job_id=job_id,
                    available_at=utc_now() + timedelta(seconds=delay),
                    error_code=details.error_code.value,
                    error_message=details.safe_message,
                )
            else:
                await job_repo.mark_failed(
                    job_id=job_id,
                    error_code=details.error_code.value,
                    error_message=details.safe_message,
                )
        return False
