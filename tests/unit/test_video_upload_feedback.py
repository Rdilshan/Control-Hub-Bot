"""Owner feedback for batches of separate video posts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import video_upload_feedback as feedback_module


class FeedbackRedis:
    def __init__(self):
        self.hashes = {}
        self.due = {}
        self.locks = {}

    def pipeline(self, transaction=True):
        parent = self

        class Pipeline:
            def __init__(self):
                self.operations = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                pass

            def delete(self, key):
                self.operations.append(("delete", key))

            def zrem(self, name, key):
                self.operations.append(("zrem", name, key))

            def hset(self, key, mapping):
                self.operations.append(("hset", key, mapping))

            def expire(self, key, ttl):
                pass

            async def execute(self):
                for operation in self.operations:
                    if operation[0] == "delete":
                        parent.hashes.pop(operation[1], None)
                    elif operation[0] == "zrem":
                        parent.due.pop(operation[2], None)
                    else:
                        await parent.hset(operation[1], mapping=operation[2])

        return Pipeline()

    def lock(self, key, **_):
        return self.locks.setdefault(key, asyncio.Lock())

    async def hset(self, key, field=None, value=None, mapping=None):
        row = self.hashes.setdefault(key, {})
        row.update({name: str(val) for name, val in (mapping or {field: value}).items()})

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def zrangebyscore(self, name, minimum, maximum, start=0, num=100):
        return [key for key, due in sorted(self.due.items(), key=lambda item: item[1]) if due <= float(maximum)][start:start + num]

    async def zadd(self, name, mapping):
        self.due.update(mapping)

    async def eval(self, script, count, key, due_key, *args):
        if script == feedback_module._RECORD_SCRIPT:
            row = self.hashes.setdefault(key, {"count": "0", "chat_id": str(args[0])})
            row["count"] = str(int(row["count"]) + 1)
            row["last_at"] = str(args[1])
            self.due[key] = float(args[1]) + int(args[3])
            return [int(row["count"]), row.get("message_id", ""), row.get("edited_at", "0")]
        if script == feedback_module._CLAIM_DUE_SCRIPT:
            if key not in self.due or self.due[key] > float(args[0]):
                return 0
            del self.due[key]
            return 1
        if script == feedback_module._FINISH_SCRIPT:
            row = self.hashes.pop(key, {})
            self.due.pop(key, None)
            return [value for pair in row.items() for value in pair]
        raise AssertionError("Unexpected Redis script")


@pytest.fixture
def feedback_setup(monkeypatch):
    redis = FeedbackRedis()
    clock = [1000.0]
    client = SimpleNamespace(
        send_message=AsyncMock(return_value={"message_id": 71}),
        edit_message_text=AsyncMock(return_value={"message_id": 71}),
    )
    monkeypatch.setattr(feedback_module, "_redis", lambda: redis)
    monkeypatch.setattr(feedback_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(feedback_module.bot_api_factory, "get_client", lambda *_: client)
    session = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(token_encrypted="encrypted")))
    return feedback_module.VideoUploadFeedback(), redis, clock, client, session


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", [1, 50, 100])
async def test_bulk_upload_uses_one_status_and_quiet_total(feedback_setup, quantity):
    feedback, redis, clock, client, session = feedback_setup
    await feedback.start(12, 34, 34)
    for _ in range(quantity):
        await feedback.accepted(12, 34, 34, client)
    assert client.send_message.await_count == 1
    assert client.edit_message_text.await_count == 0
    clock[0] += 4
    await feedback.flush_due(session)
    assert client.edit_message_text.await_count == 0
    clock[0] += 1
    await feedback.flush_due(session)
    expected_edits = 0 if quantity == 1 else 1
    assert client.edit_message_text.await_count == expected_edits
    if expected_edits:
        assert f"{quantity} videos accepted" in client.edit_message_text.call_args.kwargs["text"]
    await feedback.finish(12, 34, 34, client)
    assert client.send_message.await_count == 1
    assert f"{quantity} video" in client.edit_message_text.call_args.kwargs["text"]
    assert not redis.due


@pytest.mark.asyncio
async def test_resumed_upload_updates_same_message_and_final_count(feedback_setup):
    feedback, _, clock, client, session = feedback_setup
    await feedback.start(12, 34, 34)
    for _ in range(50):
        await feedback.accepted(12, 34, 34, client)
    clock[0] += 5
    await feedback.flush_due(session)
    for _ in range(10):
        await feedback.accepted(12, 34, 34, client)
    clock[0] += 5
    await feedback.flush_due(session)
    assert "60 videos accepted" in client.edit_message_text.call_args.kwargs["text"]
    await feedback.finish(12, 34, 34, client)
    assert "60 videos accepted" in client.edit_message_text.call_args.kwargs["text"]
    assert client.send_message.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_arrivals_and_failed_feedback_keep_count(feedback_setup):
    feedback, redis, _, client, _ = feedback_setup
    client.send_message.side_effect = [RuntimeError("Telegram unavailable"), {"message_id": 71}]
    await feedback.start(12, 34, 34)
    await asyncio.gather(*(feedback.accepted(12, 34, 34, client) for _ in range(50)))
    assert redis.hashes[feedback_module._key(12, 34)]["count"] == "50"
    assert redis.hashes[feedback_module._key(12, 34)]["message_id"] == "71"
    assert client.send_message.await_count == 2
    await feedback.finish(12, 34, 34, client)
    assert "50 videos accepted" in client.edit_message_text.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_quiet_update_retries_transient_telegram_failure(feedback_setup):
    feedback, redis, clock, client, session = feedback_setup
    await feedback.start(12, 34, 34)
    for _ in range(50):
        await feedback.accepted(12, 34, 34, client)
    client.edit_message_text.side_effect = RuntimeError("Temporary Telegram error")
    clock[0] += 5
    await feedback.flush_due(session)
    assert redis.due[feedback_module._key(12, 34)] == clock[0] + 10
    client.edit_message_text.side_effect = None
    clock[0] += 10
    await feedback.flush_due(session)
    assert "50 videos accepted" in client.edit_message_text.call_args.kwargs["text"]
    assert not redis.due


@pytest.mark.asyncio
async def test_quiet_update_recovers_initial_send_failure(feedback_setup):
    feedback, redis, clock, client, session = feedback_setup
    client.send_message.side_effect = [RuntimeError("Temporary Telegram error"), {"message_id": 71}]
    await feedback.start(12, 34, 34)
    await feedback.accepted(12, 34, 34, client)
    clock[0] += 5
    await feedback.flush_due(session)
    assert client.send_message.await_count == 2
    assert redis.hashes[feedback_module._key(12, 34)]["message_id"] == "71"
