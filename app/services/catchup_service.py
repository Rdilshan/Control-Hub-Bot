"""Catch-Up Service for orchestrating automated historical video delivery to new and returning viewers."""

from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.enums import CatchupStatus, JobType, ViewerStatus
from app.db.models.background_job import BackgroundJob
from app.db.models.client_bot import ClientBot
from app.db.models.video_processing import VideoProcessing
from app.db.models.viewer import Viewer
from app.db.models.viewer_catchup import ViewerCatchup
from app.logging_config import logger
from app.repositories.job import BackgroundJobRepository
from app.repositories.viewer import ViewerRepository
from app.repositories.viewer_catchup import ViewerCatchupRepository
from app.services.catchup_delivery_service import CatchupDeliveryService
from app.services.catchup_scheduler_service import CatchupSchedulerService
from app.services.catchup_video_selector_service import CatchupVideoSelectorService
from app.telegram.client import TelegramClient


class CatchupService:
    """Orchestrates automated, gradual catch-up delivery for viewers with rate limiting and LIVE priority."""

    def __init__(
        self,
        session: AsyncSession,
        catchup_repo: Optional[ViewerCatchupRepository] = None,
        viewer_repo: Optional[ViewerRepository] = None,
        job_repo: Optional[BackgroundJobRepository] = None,
        video_selector: Optional[CatchupVideoSelectorService] = None,
        delivery_service: Optional[CatchupDeliveryService] = None,
        scheduler_service: Optional[CatchupSchedulerService] = None,
    ):
        self.session = session
        self.catchup_repo = catchup_repo or ViewerCatchupRepository(session)
        self.viewer_repo = viewer_repo or ViewerRepository(session)
        self.job_repo = job_repo or BackgroundJobRepository(session)
        self.video_selector = video_selector or CatchupVideoSelectorService(session)
        self.delivery_service = delivery_service or CatchupDeliveryService(session)
        self.scheduler_service = scheduler_service or CatchupSchedulerService(session, self.catchup_repo)

    async def initialize_or_resume_catchup(
        self,
        client_bot_id: int,
        viewer_id: int,
    ) -> Tuple[ViewerCatchup, Optional[BackgroundJob]]:
        """Initializes or resumes catch-up state when a viewer joins or starts the bot.

        Returns:
            Tuple of (ViewerCatchup, Optional[BackgroundJob]).
        """
        catchup, is_new = await self.catchup_repo.get_or_create_catchup(
            client_bot_id=client_bot_id,
            viewer_id=viewer_id,
        )

        # 1. Capture target boundary if not set or if recovering
        if catchup.target_max_video_id is None or catchup.status == CatchupStatus.PENDING:
            max_ready_id = await self.video_selector.get_max_ready_video_id(client_bot_id)
            if not max_ready_id:
                logger.info("Bot id=%d has no READY videos for catchup on viewer id=%d", client_bot_id, viewer_id)
                await self.catchup_repo.mark_completed(viewer_id)
                await self.session.commit()
                return catchup, None

            total_eligible = await self.video_selector.count_eligible_unseen_videos(
                client_bot_id=client_bot_id,
                viewer_id=viewer_id,
                target_max_video_id=max_ready_id,
            )
            await self.catchup_repo.set_target_boundary(
                viewer_id=viewer_id,
                target_max_video_id=max_ready_id,
                total_eligible=total_eligible,
            )

            if total_eligible == 0:
                logger.info("Viewer id=%d is already caught up on bot id=%d", viewer_id, client_bot_id)
                await self.catchup_repo.mark_completed(viewer_id)
                await self.session.commit()
                return catchup, None

        # 2. Queue background catch-up job if none active
        has_job = await self.job_repo.has_active_catchup_job(client_bot_id, viewer_id)
        job = None
        if not has_job and catchup.status in (CatchupStatus.PENDING, CatchupStatus.PAUSED):
            job = await self.job_repo.create_job(
                job_type=JobType.CATCHUP,
                payload={"viewer_id": viewer_id, "client_bot_id": client_bot_id},
                client_bot_id=client_bot_id,
                queue_name="catchup",
            )
            logger.info("Queued CATCHUP job id=%d for viewer id=%d on bot id=%d", job.id, viewer_id, client_bot_id)

        await self.session.commit()
        return catchup, job

    async def process_viewer_catchup_batch(
        self,
        viewer_id: int,
        telegram_client: Optional[TelegramClient] = None,
        batch_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Processes a single batch of catch-up deliveries for a viewer.

        Args:
            viewer_id: The ID of the recipient viewer.
            telegram_client: Optional injected TelegramClient (for tests).
            batch_size: Override batch size (default from settings).

        Returns:
            Dict containing batch execution results.
        """
        settings = get_settings()
        limit = batch_size or getattr(settings, "CATCHUP_BATCH_SIZE", 10)

        # 1. Fetch catchup record, viewer, and bot
        catchup = await self.catchup_repo.get_by_viewer_id(viewer_id)
        if not catchup:
            logger.error("Catch-up record for viewer_id=%d not found", viewer_id)
            return {"ok": False, "error": "CATCHUP_NOT_FOUND"}

        viewer_stmt = select(Viewer).where(Viewer.id == viewer_id)
        viewer_res = await self.session.execute(viewer_stmt)
        viewer = viewer_res.scalar_one_or_none()

        bot_stmt = select(ClientBot).where(ClientBot.id == catchup.client_bot_id)
        bot_res = await self.session.execute(bot_stmt)
        client_bot = bot_res.scalar_one_or_none()

        if not viewer or not client_bot:
            logger.error("Missing entities for viewer_id=%d or bot_id=%d", viewer_id, catchup.client_bot_id)
            await self.catchup_repo.mark_failed(viewer_id, "MISSING_ENTITIES")
            await self.session.commit()
            return {"ok": False, "error": "MISSING_ENTITIES"}

        # 2. Check viewer block status
        if viewer.status == ViewerStatus.BLOCKED:
            logger.info("Viewer id=%d is BLOCKED. Halting catch-up.", viewer_id)
            await self.catchup_repo.mark_blocked(viewer_id)
            await self.session.commit()
            return {"ok": True, "status": CatchupStatus.BLOCKED, "message": "Viewer blocked"}

        # 3. LIVE Priority check
        if await self.scheduler_service.has_live_broadcast_in_progress(client_bot.id):
            logger.info("Bot id=%d has LIVE broadcast in progress. Pausing catch-up for viewer id=%d", client_bot.id, viewer_id)
            await self.catchup_repo.mark_paused(viewer_id, reason="LIVE_PRIORITY")
            await self.session.commit()
            return {"ok": True, "status": CatchupStatus.PAUSED, "reason": "LIVE_PRIORITY"}

        # 4. Mark RUNNING
        await self.catchup_repo.mark_running(viewer_id)
        await self.session.commit()

        # 5. Fetch next batch of eligible videos
        cursor = catchup.last_video_id or 0
        max_target = catchup.target_max_video_id

        videos = await self.video_selector.get_next_eligible_videos(
            client_bot_id=client_bot.id,
            viewer_id=viewer_id,
            cursor_video_id=cursor,
            target_max_video_id=max_target,
            limit=limit,
        )

        if not videos:
            logger.info("No more eligible catch-up videos for viewer id=%d. Marking COMPLETED.", viewer_id)
            await self.catchup_repo.mark_completed(viewer_id)
            await self.session.commit()
            return {
                "ok": True,
                "status": CatchupStatus.COMPLETED,
                "delivered_count": 0,
                "failed_count": 0,
                "completed": True,
            }

        # 6. Deliver batch
        delivered_count = 0
        failed_count = 0
        last_processed_video_id = cursor

        for video in videos:
            # Check LIVE priority mid-batch
            if await self.scheduler_service.has_live_broadcast_in_progress(client_bot.id):
                logger.info("LIVE broadcast appeared mid-batch for bot id=%d. Yielding catch-up.", client_bot.id)
                await self.catchup_repo.mark_paused(viewer_id, reason="LIVE_PRIORITY")
                break

            # Resolve video processing asset
            proc_stmt = select(VideoProcessing).where(VideoProcessing.video_id == video.id)
            proc_res = await self.session.execute(proc_stmt)
            video_proc = proc_res.scalar_one_or_none()

            status, msg_id, err_code, err_msg = await self.delivery_service.send_catchup_preview_to_viewer(
                client_bot=client_bot,
                viewer=viewer,
                video=video,
                video_processing=video_proc,
                telegram_client=telegram_client,
            )

            if status == CatchupStatus.SENT:
                delivered_count += 1
                last_processed_video_id = video.id
            elif status == CatchupStatus.BLOCKED:
                await self.catchup_repo.mark_blocked(viewer_id)
                last_processed_video_id = video.id
                break
            elif status == CatchupStatus.FAILED:
                failed_count += 1
                last_processed_video_id = video.id
            elif status == CatchupStatus.SKIPPED:
                last_processed_video_id = video.id

        # 7. Update cursor and counts in DB
        await self.catchup_repo.update_progress_and_cursor(
            viewer_id=viewer_id,
            last_video_id=last_processed_video_id,
            delivered_delta=delivered_count,
            failed_delta=failed_count,
        )

        # 8. Check remaining count
        remaining = await self.video_selector.count_eligible_unseen_videos(
            client_bot_id=client_bot.id,
            viewer_id=viewer_id,
            target_max_video_id=max_target,
        )

        is_completed = False
        if remaining == 0 and catchup.status != CatchupStatus.BLOCKED:
            await self.catchup_repo.mark_completed(viewer_id)
            is_completed = True
            logger.info("Viewer id=%d catch-up cycle COMPLETED", viewer_id)

        await self.session.commit()

        return {
            "ok": True,
            "viewer_id": viewer_id,
            "status": CatchupStatus.COMPLETED if is_completed else CatchupStatus.RUNNING,
            "delivered_count": delivered_count,
            "failed_count": failed_count,
            "remaining_count": remaining,
            "is_completed": is_completed,
        }
