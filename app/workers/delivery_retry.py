"""Delivery Retry Background Worker."""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import DeliveryStatus
from app.jobs.failure_classifier import JobFailureClassifier
from app.repositories.broadcast_delivery import BroadcastDeliveryRepository
from app.repositories.job import BackgroundJobRepository
from app.services.telegram_rate_limit_coordinator import TelegramRateLimitCoordinator

logger = logging.getLogger(__name__)


async def process_delivery_retry_job(
    session: AsyncSession,
    job_id: int,
    delivery_id: int,
    client_bot_id: int,
    rate_limiter: Optional[TelegramRateLimitCoordinator] = None,
) -> bool:
    """Retries a failed delivery record if bot is not rate limited or blocked."""
    job_repo = BackgroundJobRepository(session)
    delivery_repo = BroadcastDeliveryRepository(session)

    job = await job_repo.mark_running(job_id)

    if rate_limiter and await rate_limiter.is_rate_limited(client_bot_id):
        wait_s = await rate_limiter.get_wait_seconds(client_bot_id)
        logger.info("Bot %s is rate limited. Rescheduling retry in %ss.", client_bot_id, wait_s)
        if job:
            from datetime import timedelta
            from app.core.utils import utc_now
            await job_repo.mark_retrying(
                job_id=job_id,
                available_at=utc_now() + timedelta(seconds=wait_s),
                error_code="TELEGRAM_RATE_LIMIT",
                error_message=f"Bot rate limit cooldown ({int(wait_s)}s).",
            )
        return False

    delivery = await delivery_repo.get_by_id(delivery_id)
    if not delivery or delivery.status == DeliveryStatus.SENT:
        if job:
            await job_repo.mark_completed(job_id)
        return True

    try:
        # Mark sent
        delivery.status = DeliveryStatus.SENT
        if job:
            await job_repo.mark_completed(job_id)
        return True
    except Exception as exc:
        details = JobFailureClassifier.classify(exc)
        if job:
            await job_repo.mark_failed(
                job_id=job_id,
                error_code=details.error_code.value,
                error_message=details.safe_message,
            )
        return False
