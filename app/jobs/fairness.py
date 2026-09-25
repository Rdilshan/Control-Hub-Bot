"""Fair Scheduling and Multi-Tenant Concurrency Control."""

from collections import defaultdict
from typing import Dict, List, Optional
from app.core.enums import JobType
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob


class FairSchedulingService:
    """Provides multi-tenant fairness and concurrency caps across clients and bots."""

    def __init__(
        self,
        max_active_video_processing_per_client: int = 3,
        max_active_broadcasts_per_bot: int = 1,
        max_active_catchup_per_bot: int = 5,
        max_active_catchup_per_client: int = 20,
    ):
        self.max_video_processing_per_client = max_active_video_processing_per_client
        self.max_broadcasts_per_bot = max_active_broadcasts_per_bot
        self.max_catchup_per_bot = max_active_catchup_per_bot
        self.max_catchup_per_client = max_active_catchup_per_client

    def can_dispatch_job(
        self,
        job: BackgroundJob,
        active_video_processing_by_client: Optional[Dict[int, int]] = None,
        active_broadcasts_by_bot: Optional[Dict[int, int]] = None,
        active_catchup_by_bot: Optional[Dict[int, int]] = None,
        active_catchup_by_client: Optional[Dict[int, int]] = None,
    ) -> bool:
        """Determines if a candidate job can be dispatched without exceeding concurrency limits."""
        client_id = job.client_id
        client_bot_id = job.client_bot_id

        # 1. Video processing per-client cap
        if job.job_type in (JobType.VIDEO_PROCESS, JobType.CREATE_UNLOCK_LINK, JobType.UNLOCKIFY_CREATE_LINK):
            if client_id and active_video_processing_by_client:
                current_active = active_video_processing_by_client.get(client_id, 0)
                if current_active >= self.max_video_processing_per_client:
                    return False

        # 2. LIVE broadcast per-bot serialization (1 active per bot)
        if job.job_type in (JobType.BROADCAST, JobType.LIVE_BROADCAST):
            if client_bot_id and active_broadcasts_by_bot:
                current_active = active_broadcasts_by_bot.get(client_bot_id, 0)
                if current_active >= self.max_broadcasts_per_bot:
                    return False

        # 3. Catch-Up per-bot and per-client caps
        if job.job_type in (JobType.CATCHUP, JobType.CATCHUP_BATCH):
            if client_bot_id and active_catchup_by_bot:
                current_active_bot = active_catchup_by_bot.get(client_bot_id, 0)
                if current_active_bot >= self.max_catchup_per_bot:
                    return False
            if client_id and active_catchup_by_client:
                current_active_client = active_catchup_by_client.get(client_id, 0)
                if current_active_client >= self.max_catchup_per_client:
                    return False

        return True

    def reorder_for_fairness(self, jobs: List[BackgroundJob]) -> List[BackgroundJob]:
        """Reorders candidate pending jobs using round-robin across tenants while respecting priority.

        This guarantees that a single client with 10,000 jobs does not starve other clients with 2 jobs.
        """
        if not jobs:
            return []

        # Separate jobs by priority bracket
        # Priority >= 80 (Telegram updates, LIVE broadcasts)
        # Priority 40-79 (Video processing, lifecycle, retries)
        # Priority < 40 (Catch-Up, maintenance)
        high_priority: List[BackgroundJob] = []
        normal_priority: List[BackgroundJob] = []
        low_priority: List[BackgroundJob] = []

        now = utc_now()

        for job in jobs:
            # Check if low priority job has been waiting a long time (> 60s) -> promote to avoid starvation
            age_seconds = 0.0
            if job.scheduled_at:
                sched = job.scheduled_at
                if sched.tzinfo is None:
                    from datetime import timezone
                    sched = sched.replace(tzinfo=timezone.utc)
                age_seconds = (now - sched).total_seconds()

            p = job.priority
            if job.job_type in (JobType.TELEGRAM_UPDATE_PROCESS, JobType.BROADCAST, JobType.LIVE_BROADCAST):
                high_priority.append(job)
            elif age_seconds > 60.0 or p >= 40:
                normal_priority.append(job)
            else:
                low_priority.append(job)

        def round_robin_by_client(job_list: List[BackgroundJob]) -> List[BackgroundJob]:
            if not job_list:
                return []
            client_buckets: Dict[Optional[int], List[BackgroundJob]] = defaultdict(list)
            for j in job_list:
                client_buckets[j.client_id].append(j)

            ordered: List[BackgroundJob] = []
            active_clients = list(client_buckets.keys())
            idx = 0
            while any(len(b) > 0 for b in client_buckets.values()):
                client = active_clients[idx % len(active_clients)]
                if client_buckets[client]:
                    ordered.append(client_buckets[client].pop(0))
                idx += 1
            return ordered

        result = (
            round_robin_by_client(high_priority)
            + round_robin_by_client(normal_priority)
            + round_robin_by_client(low_priority)
        )
        return result
