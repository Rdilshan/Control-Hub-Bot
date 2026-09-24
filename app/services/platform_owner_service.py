"""Platform Owner Service providing platform-wide statistics, monitoring, and controls."""

from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    BroadcastStatus,
    ClientBotStatus,
    ClientStatus,
    JobStatus,
    JobType,
)
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.broadcast import Broadcast
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.logging_config import get_logger
from app.repositories.broadcast import BroadcastRepository
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository
from app.repositories.viewer import ViewerRepository

logger = get_logger(__name__)


class PlatformOwnerService:
    """Encapsulates all Platform Owner business logic, data aggregations, and administrative actions."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.client_repo = ClientRepository(session)
        self.bot_repo = ClientBotRepository(session)
        self.job_repo = BackgroundJobRepository(session)
        self.broadcast_repo = BroadcastRepository(session)
        self.viewer_repo = ViewerRepository(session)
        self.video_repo = VideoRepository(session)

    def _get_start_of_today_utc(self) -> datetime:
        now = utc_now()
        return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    # --- 1. Clients Management ---

    async def get_client_summary(self) -> Dict[str, Any]:
        today_start = self._get_start_of_today_utc()
        total = await self.client_repo.count_all()
        active = await self.client_repo.count_by_status(ClientStatus.ACTIVE)
        suspended = await self.client_repo.count_by_status(ClientStatus.SUSPENDED)
        disabled = await self.client_repo.count_by_status(ClientStatus.DISABLED)
        new_today = await self.client_repo.count_created_since(today_start)

        return {
            "total": total,
            "active": active,
            "suspended": suspended,
            "disabled": disabled,
            "new_today": new_today,
        }

    async def list_clients(
        self,
        page: int = 1,
        page_size: int = 10,
        status: Optional[ClientStatus] = None,
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        """Returns (items, total_count, total_pages)."""
        clients, total_count = await self.client_repo.list_paginated(
            page=page, page_size=page_size, status=status
        )
        total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count > 0 else 1

        items = []
        for client in clients:
            bots = await self.bot_repo.list_by_client(client.id)
            items.append({
                "client": client,
                "bot_count": len(bots),
            })

        return items, total_count, total_pages

    async def search_clients(self, query: str) -> List[Dict[str, Any]]:
        clients = await self.client_repo.search(query)
        items = []
        for client in clients:
            bots = await self.bot_repo.list_by_client(client.id)
            items.append({
                "client": client,
                "bot_count": len(bots),
            })
        return items

    async def get_client_detail(self, client_id: int) -> Optional[Dict[str, Any]]:
        client = await self.client_repo.get_by_id(client_id)
        if not client:
            return None

        bots = await self.bot_repo.list_by_client(client.id)
        total_viewers = await self.viewer_repo.count_by_client(client.id)
        total_videos = await self.video_repo.count_by_client(client.id)

        return {
            "client": client,
            "bots": bots,
            "total_bots": len(bots),
            "total_viewers": total_viewers,
            "total_videos": total_videos,
        }

    async def suspend_client(
        self,
        client_id: int,
        performed_by_owner_id: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[Client]]:
        client = await self.client_repo.get_by_id(client_id)
        if not client:
            return False, "Client not found", None

        if client.status == ClientStatus.SUSPENDED:
            return False, "Client is already suspended", client

        client = await self.client_repo.suspend(client_id)
        logger.info(
            f"Owner {performed_by_owner_id} suspended client #{client_id} (@{client.username if client else 'unknown'})"
        )
        return True, "Client suspended successfully", client

    async def reactivate_client(
        self,
        client_id: int,
        performed_by_owner_id: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[Client]]:
        client = await self.client_repo.get_by_id(client_id)
        if not client:
            return False, "Client not found", None

        if client.status == ClientStatus.ACTIVE:
            return False, "Client is already active", client

        client = await self.client_repo.reactivate(client_id)
        logger.info(
            f"Owner {performed_by_owner_id} reactivated client #{client_id} (@{client.username if client else 'unknown'})"
        )
        return True, "Client reactivated successfully", client

    # --- 2. Bots Management ---

    async def get_bot_summary(self) -> Dict[str, Any]:
        total = await self.bot_repo.count_all()
        active = await self.bot_repo.count_by_status(ClientBotStatus.ACTIVE)
        paused = await self.bot_repo.count_by_status(ClientBotStatus.PAUSED)
        disconnected = await self.bot_repo.count_by_status(ClientBotStatus.DISCONNECTED)
        invalid_token = await self.bot_repo.count_by_status(ClientBotStatus.INVALID_TOKEN)

        return {
            "total": total,
            "active": active,
            "paused": paused,
            "disconnected": disconnected,
            "invalid_token": invalid_token,
        }

    async def list_bots(
        self,
        page: int = 1,
        page_size: int = 10,
        status: Optional[ClientBotStatus] = None,
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        bots, total_count = await self.bot_repo.list_paginated(
            page=page, page_size=page_size, status=status
        )
        total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count > 0 else 1

        items = []
        for bot in bots:
            owner = await self.client_repo.get_by_id(bot.client_id)
            items.append({
                "bot": bot,
                "owner": owner,
            })

        return items, total_count, total_pages

    async def search_bots(self, query: str) -> List[Dict[str, Any]]:
        bots = await self.bot_repo.search(query)
        items = []
        for bot in bots:
            owner = await self.client_repo.get_by_id(bot.client_id)
            items.append({
                "bot": bot,
                "owner": owner,
            })
        return items

    async def get_bot_detail(self, bot_id: int) -> Optional[Dict[str, Any]]:
        bot = await self.bot_repo.get_by_id(bot_id)
        if not bot:
            return None

        owner = await self.client_repo.get_by_id(bot.client_id)
        users_count = await self.viewer_repo.count_by_bot(bot.id)
        videos_count = await self.video_repo.count_by_bot(bot.id)
        broadcasts_count = await self.broadcast_repo.count_by_bot(bot.id, BroadcastStatus.RUNNING)

        return {
            "bot": bot,
            "owner": owner,
            "users_count": users_count,
            "videos_count": videos_count,
            "running_broadcasts": broadcasts_count,
        }

    # --- 3. Background Jobs Management ---

    async def get_job_summary(self) -> Dict[str, Any]:
        today_start = self._get_start_of_today_utc()
        queued = await self.job_repo.count_by_status(JobStatus.PENDING)
        running = await self.job_repo.count_by_status(JobStatus.RUNNING)
        retrying = await self.job_repo.count_by_status(JobStatus.RETRYING)
        completed_today = await self.job_repo.count_completed_since(today_start)
        failed = await self.job_repo.count_by_status(JobStatus.FAILED)

        return {
            "queued": queued,
            "running": running,
            "retrying": retrying,
            "completed_today": completed_today,
            "failed": failed,
        }

    async def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        jobs, total_count = await self.job_repo.list_paginated(
            status=status, page=page, page_size=page_size
        )
        total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count > 0 else 1

        items = []
        for job in jobs:
            bot = await self.bot_repo.get_by_id(job.client_bot_id) if job.client_bot_id else None
            items.append({
                "job": job,
                "bot": bot,
            })

        return items, total_count, total_pages

    async def get_job_detail(self, job_id: int) -> Optional[Dict[str, Any]]:
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            return None

        bot = await self.bot_repo.get_by_id(job.client_bot_id) if job.client_bot_id else None
        return {
            "job": job,
            "bot": bot,
        }

    async def retry_job(
        self,
        job_id: int,
        performed_by_owner_id: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[BackgroundJob]]:
        success, msg, job = await self.job_repo.retry_job(job_id)
        if success:
            logger.info(f"Owner {performed_by_owner_id} retried background job #{job_id}")
        return success, msg, job

    # --- 4. Queue Status ---

    async def get_queue_summary(self) -> Dict[str, Any]:
        video_processing = await self.job_repo.count_by_type(JobType.VIDEO_PROCESS, JobStatus.PENDING)
        unlock_links = await self.job_repo.count_by_type(JobType.CREATE_UNLOCK_LINK, JobStatus.PENDING)
        broadcasts = await self.job_repo.count_by_type(JobType.BROADCAST, JobStatus.PENDING)
        catchup = await self.job_repo.count_by_type(JobType.CATCHUP, JobStatus.PENDING)
        retrying = await self.job_repo.count_by_status(JobStatus.RETRYING)


        oldest_job = await self.job_repo.get_oldest_queued()
        oldest_wait_str = "None"
        if oldest_job and oldest_job.scheduled_at:
            delta = utc_now() - oldest_job.scheduled_at
            seconds = int(delta.total_seconds())
            if seconds < 60:
                oldest_wait_str = f"{seconds}s"
            elif seconds < 3600:
                oldest_wait_str = f"{seconds // 60}m {seconds % 60}s"
            else:
                oldest_wait_str = f"{seconds // 3600}h {(seconds % 3600) // 60}m"

        return {
            "video_processing": video_processing,
            "unlock_links": unlock_links,
            "broadcasts": broadcasts,
            "catchup": catchup,
            "retrying": retrying,
            "oldest_waiting": oldest_wait_str,
        }

    # --- 5. Broadcasts Management ---

    async def get_broadcast_summary(self) -> Dict[str, Any]:
        today_start = self._get_start_of_today_utc()
        running = await self.broadcast_repo.count_by_status(BroadcastStatus.RUNNING)
        waiting = await self.broadcast_repo.count_by_status(BroadcastStatus.PENDING)
        completed_today = await self.broadcast_repo.count_completed_since(today_start)
        partial = await self.broadcast_repo.count_by_status(BroadcastStatus.PARTIAL)
        failed = await self.broadcast_repo.count_by_status(BroadcastStatus.FAILED)

        return {
            "running": running,
            "waiting": waiting,
            "completed_today": completed_today,
            "partial": partial,
            "failed": failed,
        }

    async def list_broadcasts(
        self,
        status: Optional[BroadcastStatus] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        bcasts, total_count = await self.broadcast_repo.list_paginated(
            status=status, page=page, page_size=page_size
        )
        total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count > 0 else 1

        items = []
        for bcast in bcasts:
            bot = await self.bot_repo.get_by_id(bcast.client_bot_id)
            items.append({
                "broadcast": bcast,
                "bot": bot,
            })

        return items, total_count, total_pages

    async def get_broadcast_detail(self, broadcast_id: int) -> Optional[Dict[str, Any]]:
        bcast = await self.broadcast_repo.get_by_id(broadcast_id)
        if not bcast:
            return None

        bot = await self.bot_repo.get_by_id(bcast.client_bot_id)
        return {
            "broadcast": bcast,
            "bot": bot,
        }

    # --- 6. Platform System Stats ---

    async def get_system_stats(self) -> Dict[str, Any]:
        today_start = self._get_start_of_today_utc()

        # Platform Totals
        total_clients = await self.client_repo.count_all()
        total_bots = await self.bot_repo.count_all()
        total_viewers = await self.viewer_repo.count_platform_total()
        total_videos = await self.video_repo.count_platform_total()

        # Operational Workload
        running_jobs = await self.job_repo.count_by_status(JobStatus.RUNNING)
        queued_jobs = await self.job_repo.count_by_status(JobStatus.PENDING)
        running_broadcasts = await self.broadcast_repo.count_by_status(BroadcastStatus.RUNNING)
        failed_jobs = await self.job_repo.count_by_status(JobStatus.FAILED)

        # Today Activity
        new_clients_today = await self.client_repo.count_created_since(today_start)
        new_bots_today = await self.bot_repo.count_created_since(today_start)
        new_viewers_today = await self.viewer_repo.count_created_since(today_start)
        videos_created_today = await self.video_repo.count_created_since(today_start)

        return {
            "total_clients": total_clients,
            "total_bots": total_bots,
            "total_viewers": total_viewers,
            "total_videos": total_videos,
            "running_jobs": running_jobs,
            "queued_jobs": queued_jobs,
            "running_broadcasts": running_broadcasts,
            "failed_jobs": failed_jobs,
            "new_clients_today": new_clients_today,
            "new_bots_today": new_bots_today,
            "new_viewers_today": new_viewers_today,
            "videos_created_today": videos_created_today,
        }
