"""Coalesced owner feedback for /createvideo uploads."""

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.client_bot import ClientBot
from app.logging_config import get_logger
from app.redis import client as redis_client
from app.telegram.client import TelegramClient
from app.telegram.client_bot.factory import bot_api_factory

logger = get_logger(__name__)

FEEDBACK_PREFIX = "controlhub:clientbot:video-feedback:"
FEEDBACK_DUE = f"{FEEDBACK_PREFIX}due"
FEEDBACK_TTL = 1800
QUIET_SECONDS = 5
EDIT_INTERVAL_SECONDS = 2

_RECORD_SCRIPT = """
if redis.call('exists', KEYS[1]) == 0 then
  redis.call('hset', KEYS[1], 'count', 0, 'chat_id', ARGV[1])
end
local count = redis.call('hincrby', KEYS[1], 'count', 1)
redis.call('hset', KEYS[1], 'last_at', ARGV[2])
redis.call('expire', KEYS[1], ARGV[3])
redis.call('zadd', KEYS[2], ARGV[2] + ARGV[4], KEYS[1])
return {count, redis.call('hget', KEYS[1], 'message_id') or '', redis.call('hget', KEYS[1], 'edited_at') or '0'}
"""

_CLAIM_DUE_SCRIPT = """
local due = redis.call('zscore', KEYS[2], KEYS[1])
if not due or tonumber(due) > tonumber(ARGV[1]) then return 0 end
redis.call('zrem', KEYS[2], KEYS[1])
return 1
"""

_FINISH_SCRIPT = """
local data = redis.call('hgetall', KEYS[1])
redis.call('del', KEYS[1])
redis.call('zrem', KEYS[2], KEYS[1])
return data
"""


@dataclass
class _LocalFeedback:
    count: int = 0
    message_id: Optional[int] = None
    edited_at: float = 0
    last_at: float = 0
    chat_id: int = 0
    displayed_count: int = 0


_local_feedback: dict[str, _LocalFeedback] = {}
_local_lock = asyncio.Lock()


@asynccontextmanager
async def _message_lock(redis, key: str):
    if redis is not None:
        async with redis.lock(f"{key}:message-lock", timeout=60, blocking_timeout=35):
            yield
    else:
        async with _local_lock:
            yield


def _key(bot_id: int, user_id: int) -> str:
    return f"{FEEDBACK_PREFIX}{bot_id}:{user_id}"


def _redis():
    client = redis_client.get_redis()
    return client if all(hasattr(client, name) for name in ("eval", "pipeline", "lock", "zrangebyscore")) else None


def _status(count: int, final: bool = False) -> str:
    if final:
        return f"<b>Upload session closed.</b> {count} video{'s' if count != 1 else ''} accepted for processing."
    return (
        f"<b>{count} video{'s' if count != 1 else ''} accepted for processing.</b>\n"
        "Send more videos, or use /cancel when finished."
    )


def _fields(values: list[str]) -> dict[str, str]:
    return dict(zip(values[::2], values[1::2]))


class VideoUploadFeedback:
    async def start(self, bot_id: int, user_id: int, chat_id: int) -> None:
        key = _key(bot_id, user_id)
        try:
            redis = _redis()
            if redis is not None:
                async with redis.pipeline(transaction=True) as pipe:
                    pipe.delete(key)
                    pipe.zrem(FEEDBACK_DUE, key)
                    pipe.hset(key, mapping={"count": 0, "chat_id": chat_id})
                    pipe.expire(key, FEEDBACK_TTL)
                    await pipe.execute()
        except Exception:
            logger.warning("Redis unavailable for video upload feedback; using process-local fallback", exc_info=True)
        async with _local_lock:
            _local_feedback[key] = _LocalFeedback(chat_id=chat_id)

    async def accepted(self, bot_id: int, user_id: int, chat_id: int, client: TelegramClient) -> None:
        """Called only after the video transaction commits; Telegram feedback is best effort."""
        key = _key(bot_id, user_id)
        now = time.time()
        redis = None
        try:
            redis = _redis()
            if redis is not None:
                result = await redis.eval(_RECORD_SCRIPT, 2, key, FEEDBACK_DUE, chat_id, now, FEEDBACK_TTL, QUIET_SECONDS)
                async with _local_lock:
                    state = _local_feedback.setdefault(key, _LocalFeedback(chat_id=chat_id))
                    state.count, state.last_at = int(result[0]), now
        except Exception:
            logger.warning("Could not record upload feedback in Redis; using process-local fallback", exc_info=True)
            redis = None
        if redis is None:
            async with _local_lock:
                state = _local_feedback.setdefault(key, _LocalFeedback(chat_id=chat_id))
                state.count += 1
                state.last_at = now

        try:
            async with _message_lock(redis, key):
                if redis:
                    current = await redis.hgetall(key)
                    if not current:
                        return
                    count = int(current["count"])
                    message_id = int(current.get("message_id") or 0)
                    edited_at = float(current.get("edited_at") or 0)
                    displayed = int(current.get("displayed_count") or 0)
                else:
                    state = _local_feedback.get(key)
                    if not state:
                        return
                    count, message_id, edited_at = state.count, state.message_id or 0, state.edited_at
                    displayed = getattr(state, "displayed_count", 0)
                if not message_id:
                    result = await client.send_message(chat_id=chat_id, text=_status(count))
                    new_id = result.get("message_id") if isinstance(result, dict) else None
                    if not new_id:
                        raise ValueError("Telegram did not return a status message ID")
                    if redis:
                        await redis.hset(key, mapping={"message_id": new_id, "edited_at": now, "displayed_count": count})
                    else:
                        state.message_id, state.edited_at, state.displayed_count = int(new_id), now, count
                elif count % 10 == 0 and count != displayed and now - edited_at >= EDIT_INTERVAL_SECONDS:
                    await client.edit_message_text(chat_id=chat_id, message_id=message_id, text=_status(count))
                    if redis:
                        await redis.hset(key, mapping={"edited_at": now, "displayed_count": count})
                    else:
                        state.edited_at, state.displayed_count = now, count
        except Exception:
            logger.warning("Video saved but upload status could not be updated for bot %s", bot_id, exc_info=True)

    async def finish(self, bot_id: int, user_id: int, chat_id: int, client: TelegramClient) -> None:
        key = _key(bot_id, user_id)
        values = {}
        try:
            redis = _redis()
            if redis is not None:
                async with _message_lock(redis, key):
                    values = _fields(await redis.eval(_FINISH_SCRIPT, 2, key, FEEDBACK_DUE))
                    await self._send_final(values, key, chat_id, bot_id, client)
                    return
        except Exception:
            logger.warning("Could not finish upload feedback in Redis", exc_info=True)
        async with _local_lock:
            local = _local_feedback.pop(key, None)
        count = int(values.get("count", local.count if local else 0))
        message_id = int(values.get("message_id") or (local.message_id if local else 0) or 0)
        await self._edit_or_send_final(bot_id, chat_id, count, message_id, client)

    async def _send_final(self, values: dict[str, str], key: str, chat_id: int, bot_id: int, client: TelegramClient) -> None:
        async with _local_lock:
            local = _local_feedback.pop(key, None)
        count = int(values.get("count", local.count if local else 0))
        message_id = int(values.get("message_id") or (local.message_id if local else 0) or 0)
        await self._edit_or_send_final(bot_id, chat_id, count, message_id, client)

    async def _edit_or_send_final(self, bot_id: int, chat_id: int, count: int, message_id: int, client: TelegramClient) -> None:
        if message_id:
            try:
                await client.edit_message_text(chat_id=chat_id, message_id=message_id, text=_status(count, final=True))
                return
            except Exception:
                logger.warning("Could not edit final upload status for bot %s", bot_id, exc_info=True)
        try:
            await client.send_message(chat_id=chat_id, text=_status(count, final=True))
        except Exception:
            logger.warning("Could not send final upload status for bot %s", bot_id, exc_info=True)

    async def flush_due(self, session: AsyncSession) -> None:
        """Run from the scheduler; the five-second deadline survives webhook completion."""
        try:
            redis = _redis()
            if redis is None:
                return
            now = time.time()
            keys = await redis.zrangebyscore(FEEDBACK_DUE, "-inf", now, start=0, num=100)
        except Exception:
            logger.warning("Could not read pending upload feedback", exc_info=True)
            return
        for key in keys:
            try:
                async with _message_lock(redis, key):
                    if not await redis.eval(_CLAIM_DUE_SCRIPT, 2, key, FEEDBACK_DUE, now):
                        continue
                    values = await redis.hgetall(key)
                    if not values:
                        continue
                    count = int(values["count"])
                    if values.get("message_id") and count == int(values.get("displayed_count") or 0):
                        continue
                    bot_id = int(key[len(FEEDBACK_PREFIX):].split(":", 1)[0])
                    bot = await session.get(ClientBot, bot_id)
                    if not bot or not bot.token_encrypted:
                        continue
                    client = bot_api_factory.get_client(bot_id, bot.token_encrypted)
                    if not client:
                        continue
                    if values.get("message_id"):
                        await client.edit_message_text(
                            chat_id=int(values["chat_id"]), message_id=int(values["message_id"]), text=_status(count),
                        )
                        await redis.hset(key, mapping={"edited_at": now, "displayed_count": count})
                    else:
                        result = await client.send_message(chat_id=int(values["chat_id"]), text=_status(count))
                        new_id = result.get("message_id") if isinstance(result, dict) else None
                        if not new_id:
                            raise ValueError("Telegram did not return a status message ID")
                        await redis.hset(key, mapping={"message_id": new_id, "edited_at": now, "displayed_count": count})
            except Exception:
                logger.warning("Could not publish quiet upload total for %s", key, exc_info=True)
                try:
                    if await redis.hgetall(key):
                        await redis.zadd(FEEDBACK_DUE, {key: now + 10})
                except Exception:
                    logger.warning("Could not reschedule upload feedback for %s", key, exc_info=True)
