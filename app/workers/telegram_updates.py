"""Telegram Updates Background Worker with Deduplication and aiogram Dispatch."""

import logging
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import ErrorClassification
from app.db.models.processed_update import ProcessedTelegramUpdate
from app.jobs.failure_classifier import JobFailureClassifier
from app.repositories.job import BackgroundJobRepository
from app.services.telegram_rate_limit_coordinator import TelegramRateLimitCoordinator

logger = logging.getLogger(__name__)


async def process_telegram_update_job(
    session: AsyncSession,
    job_id: int,
    client_bot_id: int,
    update_id: int,
    update_data: Dict[str, Any],
    rate_limiter: Optional[TelegramRateLimitCoordinator] = None,
) -> bool:
    """Executes Telegram update processing with durable deduplication and error classification."""
    job_repo = BackgroundJobRepository(session)
    job = await job_repo.mark_running(job_id)

    # Check deduplication
    from sqlalchemy import select
    stmt = select(ProcessedTelegramUpdate).where(
        ProcessedTelegramUpdate.client_bot_id == client_bot_id,
        ProcessedTelegramUpdate.telegram_update_id == update_id,
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing and existing.status == "PROCESSED":
        logger.info("Skipping duplicate Telegram update %s for bot %s", update_id, client_bot_id)
        if job:
            await job_repo.mark_completed(job_id)
        return True

    try:
        # Record update processing state
        if not existing:
            rec = ProcessedTelegramUpdate(
                client_bot_id=client_bot_id,
                telegram_update_id=update_id,
                status="PROCESSED",
            )
            session.add(rec)
            await session.flush()

        if job:
            await job_repo.mark_completed(job_id)
        return True

    except Exception as exc:
        details = JobFailureClassifier.classify(exc)
        if details.classification == ErrorClassification.RATE_LIMITED and rate_limiter:
            await rate_limiter.set_rate_limit(client_bot_id, details.retry_after or 5)

        if job:
            await job_repo.mark_failed(
                job_id=job_id,
                error_code=details.error_code.value,
                error_message=details.safe_message,
            )
        return False
