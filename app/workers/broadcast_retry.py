"""Broadcast Retry Worker for re-dispatching failed broadcast deliveries."""

from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.logging_config import logger
from app.services.broadcast_service import BroadcastService


class BroadcastRetryWorker:
    """Worker for retrying failed deliveries within an active or partial broadcast."""

    def __init__(
        self,
        session: AsyncSession,
        broadcast_service: Optional[BroadcastService] = None,
    ):
        self.session = session
        self.service = broadcast_service or BroadcastService(session)

    async def process_retry(
        self,
        broadcast_id: int,
        max_attempts: int = 3,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Executes a batch retry for failed deliveries on a broadcast."""
        try:
            return await self.service.retry_failed_deliveries(
                broadcast_id=broadcast_id,
                max_attempts=max_attempts,
                limit=limit,
            )
        except Exception as exc:
            logger.exception("Error during broadcast retry for broadcast_id=%d: %s", broadcast_id, exc)
            return {"ok": False, "error": "RETRY_EXECUTION_ERROR", "message": str(exc)}
