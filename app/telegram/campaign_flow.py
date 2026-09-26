"""Short-lived Telegram compose state for custom broadcasts."""

import json
from typing import Any, Optional
from app.redis.client import get_redis

PREFIX = "controlhub:campaign:draft:"
TTL = 1800
_fallback: dict[str, str] = {}


async def get_draft(scope: str, user_id: int) -> Optional[dict[str, Any]]:
    key = f"{PREFIX}{scope}:{user_id}"
    try:
        value = await get_redis().get(key)
    except Exception:
        value = _fallback.get(key)
    return json.loads(value) if value else None


async def set_draft(scope: str, user_id: int, draft: dict[str, Any]) -> None:
    key = f"{PREFIX}{scope}:{user_id}"
    try:
        await get_redis().set(key, json.dumps(draft), ex=TTL)
    except Exception:
        _fallback[key] = json.dumps(draft)


async def clear_draft(scope: str, user_id: int) -> None:
    key = f"{PREFIX}{scope}:{user_id}"
    try:
        await get_redis().delete(key)
    except Exception:
        _fallback.pop(key, None)


def draft_keyboard(scope: str) -> dict[str, Any]:
    return {"inline_keyboard": [[
        {"text": "Send broadcast", "callback_data": f"{scope}:campaign:confirm"},
        {"text": "Cancel", "callback_data": f"{scope}:campaign:cancel"},
    ]]}


def progress_text(detail: dict[str, Any]) -> str:
    return (
        f"<b>Broadcast #{detail['id']}</b> ({detail['audience']})\n"
        f"Status: {detail['status']}\n"
        f"Total: {detail['total']:,} | Sent: {detail['sent']:,}\n"
        f"Failed: {detail['failed']:,} | Blocked: {detail['blocked']:,}\n"
        f"Remaining: {detail['remaining']:,}"
    )
