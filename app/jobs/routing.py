"""Queue Routing and Priority Definitions."""

from typing import Dict
from app.core.enums import JobType


class QueueNames:
    TELEGRAM_UPDATES = "telegram_updates"
    VIDEO_PROCESSING = "video_processing"
    UNLOCKIFY = "unlockify"
    BROADCAST_LIVE = "broadcast_live"
    CATCHUP = "catchup"
    DELIVERY_RETRY = "delivery_retry"
    LIFECYCLE = "lifecycle"
    MAINTENANCE = "maintenance"
    DEFAULT = "default"


JOB_TYPE_TO_QUEUE: Dict[JobType, str] = {
    JobType.TELEGRAM_UPDATE_PROCESS: QueueNames.TELEGRAM_UPDATES,
    JobType.VIDEO_PROCESS: QueueNames.VIDEO_PROCESSING,
    JobType.CREATE_UNLOCK_LINK: QueueNames.UNLOCKIFY,
    JobType.UNLOCKIFY_CREATE_LINK: QueueNames.UNLOCKIFY,
    JobType.BROADCAST: QueueNames.BROADCAST_LIVE,
    JobType.OWNER_MESSAGE_CAMPAIGN: QueueNames.BROADCAST_LIVE,
    JobType.LIVE_BROADCAST: QueueNames.BROADCAST_LIVE,
    JobType.CATCHUP: QueueNames.CATCHUP,
    JobType.CATCHUP_BATCH: QueueNames.CATCHUP,
    JobType.RETRY: QueueNames.DELIVERY_RETRY,
    JobType.DELIVERY_RETRY: QueueNames.DELIVERY_RETRY,
    JobType.UNLOCK_VIDEO_DELIVERY: QueueNames.BROADCAST_LIVE,
    JobType.CLIENT_BOT_PROVISION: QueueNames.LIFECYCLE,
    JobType.CLIENT_BOT_DISCONNECT: QueueNames.LIFECYCLE,
    JobType.CLIENT_BOT_RECONNECT: QueueNames.LIFECYCLE,
    JobType.CLIENT_BOT_HEALTH_CHECK: QueueNames.LIFECYCLE,
    JobType.CLIENT_BOT_LIFECYCLE_RECONCILE: QueueNames.LIFECYCLE,
    JobType.CLIENT_BOT_RESUME_WORK: QueueNames.LIFECYCLE,
    JobType.LIFECYCLE_RECOVERY: QueueNames.MAINTENANCE,
    JobType.BROADCAST_RECOVERY: QueueNames.MAINTENANCE,
    JobType.CATCHUP_RECOVERY: QueueNames.MAINTENANCE,
    JobType.PROCESSING_RECOVERY: QueueNames.MAINTENANCE,
    JobType.RECONCILIATION: QueueNames.MAINTENANCE,
}


JOB_TYPE_PRIORITY: Dict[JobType, int] = {
    JobType.TELEGRAM_UPDATE_PROCESS: 100,
    JobType.BROADCAST: 80,
    JobType.OWNER_MESSAGE_CAMPAIGN: 80,
    JobType.LIVE_BROADCAST: 80,
    JobType.UNLOCK_VIDEO_DELIVERY: 70,
    JobType.VIDEO_PROCESS: 60,
    JobType.CREATE_UNLOCK_LINK: 60,
    JobType.UNLOCKIFY_CREATE_LINK: 60,
    JobType.CLIENT_BOT_PROVISION: 50,
    JobType.CLIENT_BOT_DISCONNECT: 50,
    JobType.CLIENT_BOT_RECONNECT: 50,
    JobType.CLIENT_BOT_HEALTH_CHECK: 50,
    JobType.DELIVERY_RETRY: 40,
    JobType.RETRY: 40,
    JobType.CATCHUP: 30,
    JobType.CATCHUP_BATCH: 30,
    JobType.LIFECYCLE_RECOVERY: 20,
    JobType.BROADCAST_RECOVERY: 20,
    JobType.CATCHUP_RECOVERY: 20,
    JobType.PROCESSING_RECOVERY: 20,
    JobType.RECONCILIATION: 10,
    JobType.CLIENT_BOT_LIFECYCLE_RECONCILE: 10,
    JobType.CLIENT_BOT_RESUME_WORK: 50,
}


class QueueRoutingService:
    @staticmethod
    def get_queue_for_job_type(job_type: JobType) -> str:
        """Returns the mapped Celery queue name for a given job type."""
        return JOB_TYPE_TO_QUEUE.get(job_type, QueueNames.DEFAULT)

    @staticmethod
    def get_priority_for_job_type(job_type: JobType) -> int:
        """Returns numeric execution priority (higher number = higher priority)."""
        return JOB_TYPE_PRIORITY.get(job_type, 0)
