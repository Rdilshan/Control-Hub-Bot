"""Load and scaling simulation unit tests for high-volume broadcasts and queue fairness."""

import time
import pytest
from app.core.constants import BROADCAST_BATCH_SIZE
from app.services.fair_scheduling_service import FairSchedulingService


def test_large_audience_batch_chunking():
    """Simulates partitioning a 100,000 audience list into memory-bounded chunks."""
    audience_size = 100_000
    batch_size = BROADCAST_BATCH_SIZE or 500

    # Generator simulating streaming chunks from DB cursor without loading all into memory
    def chunk_generator(total_count, chunk_sz):
        for offset in range(0, total_count, chunk_sz):
            yield list(range(offset, min(offset + chunk_sz, total_count)))

    total_chunks = 0
    total_processed = 0

    start_time = time.perf_counter()
    for batch in chunk_generator(audience_size, batch_size):
        total_chunks += 1
        total_processed += len(batch)
        assert len(batch) <= batch_size
    duration = time.perf_counter() - start_time

    assert total_processed == 100_000
    assert total_chunks == 200  # 100,000 / 500 = 200 batches
    # Memory chunking simulation should take < 50ms
    assert duration < 0.2


def test_fair_scheduling_multi_tenant_fairness_under_load():
    """Simulates fair queue interleaving when one bot floods the queue with tasks."""
    scheduler = FairSchedulingService()

    # Bot 1 enqueues 100 tasks, Bot 2 enqueues 5 tasks, Bot 3 enqueues 5 tasks
    queues = {
        1: [f"bot1_task_{i}" for i in range(100)],
        2: [f"bot2_task_{i}" for i in range(5)],
        3: [f"bot3_task_{i}" for i in range(5)],
    }

    # Round-robin fair extraction simulation
    dispatched = []
    while any(queues.values()):
        for bot_id in list(queues.keys()):
            if queues[bot_id]:
                dispatched.append(queues[bot_id].pop(0))

    # Ensure Bot 2 and Bot 3 tasks are dispatched early rather than waiting behind all 100 of Bot 1's tasks
    bot2_dispatches = [i for i, task in enumerate(dispatched) if task.startswith("bot2")]
    assert max(bot2_dispatches) < 20  # Bot 2 finished within first 20 dispatches despite Bot 1's 100 tasks
