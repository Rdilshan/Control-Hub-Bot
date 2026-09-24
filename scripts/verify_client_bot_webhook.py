"""Verification utility to inspect Client Bot Webhook and Info from Telegram."""

import asyncio
import sys
from app.config import get_settings
from app.core.security import mask_bot_token
from app.telegram.client import TelegramClient


async def verify_bot(token: str) -> None:
    print(f"Inspecting bot with token: {mask_bot_token(token)}")
    client = TelegramClient(token=token)

    try:
        bot_info = await client.get_me()
        print(f"✅ getMe Successful:")
        print(f"   ID: {bot_info.id}")
        print(f"   Username: @{bot_info.username}")
        print(f"   First Name: {bot_info.first_name}")

        webhook_info = await client.get_webhook_info()
        print(f"🌐 Webhook Info:")
        print(f"   URL: {webhook_info.get('url', 'None (polling mode)')}")
        print(f"   Custom Certificate: {webhook_info.get('has_custom_certificate', False)}")
        print(f"   Pending Updates: {webhook_info.get('pending_update_count', 0)}")
        print(f"   Last Error Date: {webhook_info.get('last_error_date', 'None')}")
        print(f"   Last Error Message: {webhook_info.get('last_error_message', 'None')}")
    except Exception as exc:
        print(f"❌ Verification Failed: {exc}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/verify_client_bot_webhook.py <BOT_TOKEN>")
        sys.exit(1)

    asyncio.run(verify_bot(sys.argv[1]))
