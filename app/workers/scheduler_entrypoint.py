"""CLI and process entrypoint for background periodic scheduler."""

import asyncio
import signal
from app.db.session import AsyncSessionLocal
from app.logging_config import logger
from app.redis.client import get_redis_client
from app.services.system_monitoring_service import SystemMonitoringService
from app.workers.lifecycle import process_lifecycle_reconciliation
from app.workers.maintenance import run_maintenance_recovery_cycle


class SchedulerRunner:
    """Orchestrates periodic background jobs (recovery, reconciliation, cleanup)."""

    def __init__(self, cycle_interval: float = 30.0):
        self.cycle_interval = cycle_interval
        self._running = True

    def stop(self, *args):
        logger.info("Stopping periodic scheduler...")
        self._running = False

    async def run(self):
        logger.info("Starting periodic scheduler (cycle_interval=%.1fs)", self.cycle_interval)
        redis_client = await get_redis_client()
        monitor = SystemMonitoringService(redis_client)

        iteration = 0
        while self._running:
            try:
                iteration += 1
                # Heartbeat
                await monitor.record_heartbeat("scheduler", {"interval": self.cycle_interval, "iteration": iteration})

                # Run recovery cycle every iteration
                await run_maintenance_recovery_cycle()

                # Run lifecycle reconciliation every 5th iteration (~2.5 minutes)
                if iteration % 5 == 0:
                    async with AsyncSessionLocal() as session:
                        await process_lifecycle_reconciliation(session)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Scheduler iteration error: %s", exc)

            await asyncio.sleep(self.cycle_interval)

        logger.info("Periodic scheduler gracefully terminated.")


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
