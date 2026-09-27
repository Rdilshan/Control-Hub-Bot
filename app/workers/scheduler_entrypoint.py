"""CLI and process entrypoint for background periodic scheduler."""

import asyncio
import signal
from app.db.session import AsyncSessionLocal
from app.logging_config import logger
from app.redis.client import get_redis_client
from app.services.system_monitoring_service import SystemMonitoringService
from app.services.video_upload_feedback import VideoUploadFeedback
from app.workers.lifecycle import process_lifecycle_reconciliation
from app.workers.maintenance import run_maintenance_recovery_cycle


class SchedulerRunner:
    """Orchestrates periodic background jobs (recovery, reconciliation, cleanup)."""

    def __init__(self, cycle_interval: float = 30.0, feedback_interval: float = 2.0):
        self.cycle_interval = cycle_interval
        self.feedback_interval = feedback_interval
        self._running = True

    def stop(self, *args):
        logger.info("Stopping periodic scheduler...")
        self._running = False

    async def run(self):
        logger.info("Starting periodic scheduler (cycle_interval=%.1fs)", self.cycle_interval)
        monitor = SystemMonitoringService()
        feedback_task = asyncio.create_task(self._run_feedback())

        iteration = 0
        try:
            while self._running:
                try:
                    iteration += 1
                    await monitor.record_heartbeat("scheduler", {"interval": self.cycle_interval, "iteration": iteration})
                    await run_maintenance_recovery_cycle()
                    # Lifecycle reconciliation remains every fifth recovery cycle.
                    if iteration % 5 == 0:
                        async with AsyncSessionLocal() as session:
                            await process_lifecycle_reconciliation(session)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.exception("Scheduler iteration error: %s", exc)
                await asyncio.sleep(self.cycle_interval)
        finally:
            feedback_task.cancel()
            try:
                await feedback_task
            except asyncio.CancelledError:
                pass

        logger.info("Periodic scheduler gracefully terminated.")

    async def _run_feedback(self):
        feedback = VideoUploadFeedback()
        while self._running:
            try:
                async with AsyncSessionLocal() as session:
                    await feedback.flush_due(session)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Upload feedback scheduler error: %s", exc)
            await asyncio.sleep(self.feedback_interval)


def main():
    runner = SchedulerRunner()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runner.stop)
        except (NotImplementedError, AttributeError):
            pass

    try:
        loop.run_until_complete(runner.run())
    except KeyboardInterrupt:
        runner.stop()
    finally:
        loop.close()


if __name__ == "__main__":
    main()
