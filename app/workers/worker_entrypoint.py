"""CLI and process entrypoint for background worker loops."""

import argparse
import asyncio
import signal
from typing import Optional
from app.db.session import AsyncSessionLocal
from app.config import get_settings
from app.logging_config import logger
from app.redis.client import get_redis_client
from app.services.system_monitoring_service import SystemMonitoringService
from app.workers.catchup_worker import CatchupWorker
from app.workers.collection_delivery import CollectionDeliveryWorker
from app.workers.delivery_retry import process_delivery_retry_job
from app.workers.lifecycle_worker import LifecycleWorker
from app.workers.live_broadcast import LiveBroadcastWorker
from app.workers.owner_message_campaign import OwnerMessageCampaignWorker
from app.workers.maintenance import run_maintenance_recovery_cycle
from app.workers.video_processing import VideoProcessingWorker


class BackgroundWorkerRunner:
    """Orchestrates loop-based execution of background queues."""

    def __init__(self, queue_name: str, poll_interval: float = 2.0):
        self.queue_name = queue_name
        self.poll_interval = poll_interval
        self._running = True

    def stop(self, *args):
        logger.info("Stopping worker loop for queue=%s", self.queue_name)
        self._running = False

    async def run(self):
        logger.info("Starting worker loop for queue=%s (poll_interval=%.1fs)", self.queue_name, self.poll_interval)
        monitor = SystemMonitoringService()

        while self._running:
            try:
                # Record worker heartbeat
                await monitor.record_heartbeat(f"worker_{self.queue_name}", {"queue": self.queue_name})

                async with AsyncSessionLocal() as session:
                    if self.queue_name in ("broadcast_live", "all"):
                        owner_worker = OwnerMessageCampaignWorker(session)
                        owner_job = await owner_worker.claim_job()
                        if owner_job:
                            await owner_worker.process_job(owner_job.id)
                        else:
                            bcast_worker = LiveBroadcastWorker(session)
                            jobs = await bcast_worker.claim_jobs(limit=1)
                            for j in jobs:
                                await bcast_worker.process_job(j.id)

                    if self.queue_name in ("video_processing", "all"):
                        video_worker = VideoProcessingWorker(session)
                        v_jobs = await video_worker.get_pending_jobs(limit=5)
                        for j in v_jobs:
                            await video_worker.process_job(j.id)

                    if self.queue_name in ("catchup", "all"):
                        catchup_worker = CatchupWorker(session)
                        c_jobs = await catchup_worker.get_pending_jobs(limit=5)
                        for j in c_jobs:
                            await catchup_worker.process_job(j.id)

                    if self.queue_name in ("collection_delivery", "all"):
                        collection_worker = CollectionDeliveryWorker(session)
                        job = await collection_worker.claim()
                        if job:
                            await collection_worker.process(job.id)

                    if self.queue_name in ("lifecycle", "all"):
                        lifecycle_worker = LifecycleWorker(session)
                        l_jobs = await lifecycle_worker.get_pending_jobs(limit=5)
                        for j in l_jobs:
                            await lifecycle_worker.process_job(j.id)

                    if self.queue_name in ("maintenance", "all"):
                        await run_maintenance_recovery_cycle()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Worker iteration error for queue=%s: %s", self.queue_name, exc)

            await asyncio.sleep(self.poll_interval)

        logger.info("Worker loop gracefully terminated for queue=%s", self.queue_name)


def main():
    parser = argparse.ArgumentParser(description="Control Hub Background Worker Entrypoint")
    parser.add_argument(
        "--queue",
        choices=["all", "broadcast_live", "video_processing", "catchup", "collection_delivery", "lifecycle", "maintenance", "telegram_updates"],
        default="all",
        help="Target queue for this worker instance",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Poll interval in seconds",
    )
    args = parser.parse_args()

    runner = BackgroundWorkerRunner(queue_name=args.queue, poll_interval=args.interval)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runner.stop)
        except (NotImplementedError, AttributeError):
            # Windows signal handlers fallback
            pass

    try:
        loop.run_until_complete(runner.run())
    except KeyboardInterrupt:
        runner.stop()
    finally:
        loop.close()


if __name__ == "__main__":
    main()
