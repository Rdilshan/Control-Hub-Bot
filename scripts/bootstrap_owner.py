"""Bootstrap CLI script to create the initial Platform Owner."""

import argparse
import asyncio
import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings
from app.db.session import async_session_factory, close_db_engine, init_db_engine
from app.repositories.platform_owner import PlatformOwnerRepository


async def bootstrap_owner(telegram_user_id: int, username: str = None) -> None:
    settings = get_settings()
    init_db_engine(settings.DATABASE_URL)
    session_factory = async_session_factory()

    async with session_factory() as session:
        repo = PlatformOwnerRepository(session)
        existing = await repo.get_by_telegram_user_id(telegram_user_id)
        if existing:
            print(f"Platform owner with Telegram ID {telegram_user_id} already exists (ID: {existing.id}).")
        else:
            owner = await repo.create(telegram_user_id=telegram_user_id, username=username)
            await session.commit()
            print(f"Successfully created platform owner: {owner.telegram_user_id} (ID: {owner.id})")

    await close_db_engine()


def main():
    parser = argparse.ArgumentParser(description="Bootstrap Control Hub Platform Owner")
    parser.add_argument("--telegram-id", type=int, help="Telegram User ID of platform owner")
    parser.add_argument("--username", type=str, default=None, help="Telegram username")
    args = parser.parse_args()

    settings = get_settings()
    target_id = args.telegram_id or settings.PLATFORM_OWNER_TELEGRAM_ID
    if not target_id:
        print("Error: Please provide --telegram-id or set PLATFORM_OWNER_TELEGRAM_ID in .env")
        return

    asyncio.run(bootstrap_owner(target_id, args.username))


if __name__ == "__main__":
    main()
