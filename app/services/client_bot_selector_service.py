"""Client Bot Selector Service for reusable bot selection menus, pagination, and context caching."""

import asyncio
import json
import math
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ClientBotStatus, enum_val
from app.logging_config import logger
from app.redis.client import get_redis
from app.repositories.client_bot import ClientBotRepository

SELECTED_BOT_KEY_PREFIX = "controlhub:selected-bot:"
SELECTED_BOT_TTL = 3600  # 1 hour

_in_memory_selected_store: Dict[int, int] = {}
_selected_lock = asyncio.Lock()

STATUS_EMOJIS = {
    ClientBotStatus.ACTIVE.value: "✅",
    ClientBotStatus.PAUSED.value: "⏸",
    ClientBotStatus.DISCONNECTED.value: "🔌",
    ClientBotStatus.DISCONNECTING.value: "⏳",
    ClientBotStatus.INVALID_TOKEN.value: "⚠️",
    ClientBotStatus.UNAVAILABLE.value: "⚠️",
    ClientBotStatus.REVOKED.value: "🚫",
    ClientBotStatus.PROVISIONING.value: "⚙️",
    ClientBotStatus.PROVISION_FAILED.value: "❌",
}


class ClientBotSelectorService:
    """Manages bot selection keyboard generation and temporary selection context caching."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.bot_repo = ClientBotRepository(session)

    async def store_selected_bot(self, client_id: int, client_bot_id: int) -> bool:
        """Stores the currently selected bot context for a client."""
        key = f"{SELECTED_BOT_KEY_PREFIX}{client_id}"
        try:
            redis = get_redis()
            val = json.dumps({"client_bot_id": client_bot_id})
            await redis.set(key, val, ex=SELECTED_BOT_TTL)
            return True
        except Exception:
            async with _selected_lock:
                _in_memory_selected_store[client_id] = client_bot_id
                return True

    async def get_selected_bot(self, client_id: int) -> Optional[int]:
        """Retrieves the cached selected bot ID for a client."""
        key = f"{SELECTED_BOT_KEY_PREFIX}{client_id}"
        try:
            redis = get_redis()
            val = await redis.get(key)
            if val:
                data = json.loads(val)
                return data.get("client_bot_id")
        except Exception:
            pass

        async with _selected_lock:
            return _in_memory_selected_store.get(client_id)

    async def clear_selected_bot(self, client_id: int) -> None:
        """Clears the cached selected bot context for a client."""
        key = f"{SELECTED_BOT_KEY_PREFIX}{client_id}"
        try:
            redis = get_redis()
            await redis.delete(key)
        except Exception:
            pass

        async with _selected_lock:
            _in_memory_selected_store.pop(client_id, None)

    async def build_bot_selector_keyboard(
        self,
        client_id: int,
        page: int = 1,
        page_size: int = 5,
        action_prefix: str = "client:bot:select",
    ) -> Tuple[List[List[Dict[str, Any]]], int, int]:
        """Generates an inline keyboard listing the client's bots with pagination controls."""
        bots, total_count = await self.bot_repo.list_by_client_paginated(
            client_id=client_id,
            page=page,
            page_size=page_size,
        )

        total_pages = max(1, math.ceil(total_count / page_size))
        keyboard: List[List[Dict[str, Any]]] = []

        # Bot buttons
        for bot in bots:
            st_val = enum_val(bot.status)
            emoji = STATUS_EMOJIS.get(st_val, "🤖")
            label = f"{emoji} @{bot.username or bot.display_name or f'Bot #{bot.id}'}"
            callback_data = f"{action_prefix}:{bot.id}"
            keyboard.append([{"text": label, "callback_data": callback_data}])

        # Pagination controls
        nav_row: List[Dict[str, Any]] = []
        if page > 1:
            nav_row.append({"text": "◀ Previous", "callback_data": f"client:mybots:page:{page - 1}"})
        if page < total_pages:
            nav_row.append({"text": "Next ▶", "callback_data": f"client:mybots:page:{page + 1}"})

        if nav_row:
            keyboard.append(nav_row)

        return keyboard, total_pages, total_count
