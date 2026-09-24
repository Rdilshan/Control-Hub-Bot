"""Script to configure the Control Hub Telegram Bot webhook and command scopes."""

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.logging_config import get_logger
from app.telegram.client import TelegramClient


logger = get_logger(__name__)


async def setup_webhook() -> None:
    settings = get_settings()
    if not settings.CONTROL_HUB_BOT_TOKEN:
        print("ERROR: CONTROL_HUB_BOT_TOKEN is not set.")
        return

    client = TelegramClient(token=settings.CONTROL_HUB_BOT_TOKEN)

    # 1. Verify Bot Identity
    me = await client.get_me()
    print(f"Bot Identity: @{me.username} (ID: {me.id}, Name: {me.first_name})")

    # 2. Configure Command Scopes
    # Default Client Commands
    client_commands = [
        {"command": "start", "description": "Open Control Hub main menu"},
        {"command": "connectbot", "description": "Connect a new Telegram bot"},
        {"command": "mybots", "description": "Manage your connected bots"},
        {"command": "account", "description": "View account status and limits"},
        {"command": "help", "description": "Get help and instructions"},
    ]
    await client.set_my_commands(commands=client_commands)
    print("Registered default client commands.")

    # Platform Owner Commands (if PLATFORM_OWNER_TELEGRAM_ID is configured)
    if settings.PLATFORM_OWNER_TELEGRAM_ID:
        owner_commands = [
            {"command": "clients", "description": "View and manage clients"},
            {"command": "bots", "description": "View all platform bots"},
            {"command": "jobs", "description": "Monitor system jobs & queues"},
            {"command": "queue", "description": "View queue diagnostics"},
            {"command": "broadcasts", "description": "Manage active broadcasts"},
            {"command": "systemstats", "description": "System health & performance"},
        ]
        owner_scope = {
            "type": "chat",
            "chat_id": settings.PLATFORM_OWNER_TELEGRAM_ID,
        }
        await client.set_my_commands(commands=owner_commands, scope=owner_scope)
        print(f"Registered owner commands for user/chat ID {settings.PLATFORM_OWNER_TELEGRAM_ID}.")

    # 3. Set Webhook if URL provided
    if settings.TELEGRAM_WEBHOOK_BASE_URL:
        webhook_url = f"{settings.TELEGRAM_WEBHOOK_BASE_URL.rstrip('/')}/api/v1/webhooks/telegram/control-hub"
        print(f"Configuring webhook to: {webhook_url}")
        success = await client.set_webhook(
            url=webhook_url,
            secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
            allowed_updates=["message", "callback_query", "my_chat_member"],
        )
        if success:
            print("Webhook successfully configured!")
        else:
            print("Failed to configure webhook.")
    else:
        print("TELEGRAM_WEBHOOK_BASE_URL not set. Webhook URL was not modified.")

    # 4. Fetch Webhook Status
    info = await client.get_webhook_info()
    print(f"Current Webhook Info: {info}")


if __name__ == "__main__":
    asyncio.run(setup_webhook())
