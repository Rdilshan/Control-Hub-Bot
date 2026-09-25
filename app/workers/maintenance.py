"""Maintenance and Recovery Worker Tasks."""

import logging
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.jobs.recovery import JobRecoveryService

logger = logging.getLogger(__name__)


async def run_maintenance_recovery_cycle(session: Optional[AsyncSession] = None) -> Dict[str, Any]:
    """Executes periodic recovery of stale jobs, stranded queues, and missing domain records."""
    from app.db.session import AsyncSessionLocal

    if session is None:
        async with AsyncSessionLocal() as local_session:
            return await _execute_recovery(local_session)
    return await _execute_recovery(session)


async def _execute_recovery(session: AsyncSession) -> Dict[str, Any]:
    recovery = JobRecoveryService(session)

    stale_running = await recovery.recover_stale_running_jobs(threshold_seconds=300)
    lost_queued = await recovery.recover_lost_queued_jobs(threshold_seconds=600)
    unprocessed_videos = await recovery.reconcile_unprocessed_videos()
    missing_broadcasts = await recovery.reconcile_missing_broadcasts()
    stalled_catchups = await recovery.reconcile_stalled_catchups()

    await session.commit()

    summary = {
        "stale_running_recovered": len(stale_running),
        "lost_queued_recovered": len(lost_queued),
        "unprocessed_videos_reconciled": len(unprocessed_videos),
        "missing_broadcasts_reconciled": len(missing_broadcasts),
        "stalled_catchups_reconciled": len(stalled_catchups),
    }
    logger.info("Maintenance recovery cycle complete: %s", summary)
    return summary
