"""Script to run the Control Hub Bot locally using Telegram Long Polling."""

import asyncio
import signal
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.db.session import async_session_factory, close_db_engine, init_db_engine
from app.logging_config import get_logger
from app.telegram.client import TelegramClient
from app.telegram.control_hub.router import ControlHubRouter


logger = get_logger(__name__)


async def run_polling() -> None:
    settings = get_settings()
    if not settings.CONTROL_HUB_BOT_TOKEN:
        print("ERROR: CONTROL_HUB_BOT_TOKEN is not set.")
        return

    # Initialize Database
    init_db_engine()
    session_factory = async_session_factory()

    client = TelegramClient(token=settings.CONTROL_HUB_BOT_TOKEN)

    # 1. Verify Bot Identity
    try:
        me = await client.get_me()
        print(f"🚀 Started Control Hub Polling for @{me.username} (ID: {me.id})")
    except Exception as exc:
        print(f"ERROR: Failed to connect to Telegram: {exc}")
        await close_db_engine()
        return

    # 2. Clear any webhook before polling
    await client.delete_webhook(drop_pending_updates=False)
    print("Deleted any active webhook. Starting update polling loop (Ctrl+C to stop)...")

    router = ControlHubRouter(telegram_client=client)
    offset = 0
    running = True

    def stop_signal_handler():
        nonlocal running
        print("\nStopping polling loop...")
        running = False

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_signal_handler)
        except NotImplementedError:
            # On Windows signal handlers with asyncio can raise NotImplementedError
            pass

    try:
        while running:
            try:
                updates = await client.get_updates(offset=offset, limit=100, timeout=20)
                for update in updates:
                    update_id = update.get("update_id", 0)
                    offset = max(offset, update_id + 1)

                    async with session_factory() as session:
                        try:
                            await router.process_update(update=update, session=session)
                            await session.commit()
                        except Exception as err:
                            await session.rollback()
                            logger.error(f"Error processing update {update_id}: {err}", exc_info=True)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Polling loop encountered error: {exc}")
                await asyncio.sleep(2)

    finally:
        await close_db_engine()
        print("Control Hub Bot polling stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(run_polling())
    except KeyboardInterrupt:
        print("\nExited.")
