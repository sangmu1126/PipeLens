from unittest.mock import AsyncMock, MagicMock

import pytest

from pipelens.models import AnalysisRequest
from pipelens.queue import InMemoryAnalysisQueue, QueueEnvelope, QueueJob, RedisAnalysisQueue


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        run_id=77,
        repository="acme/widgets",
        installation_id=5,
        head_sha="abc123",
    )


@pytest.mark.asyncio
async def test_memory_queue_retries_with_incremented_attempt() -> None:
    queue = InMemoryAnalysisQueue()
    await queue.enqueue(_request())

    first = await queue.dequeue()
    await queue.retry(first)
    second = await queue.dequeue()

    assert second.envelope.request.run_id == 77
    assert second.envelope.attempts == 1
    await queue.acknowledge(second)
    assert await queue.size() == 0


@pytest.mark.asyncio
async def test_redis_queue_acknowledges_processing_receipt() -> None:
    redis = MagicMock()
    envelope = QueueEnvelope(request=_request())
    redis.brpoplpush = AsyncMock(return_value=envelope.model_dump_json())
    redis.lrem = AsyncMock()
    queue = RedisAnalysisQueue(redis, "analyses")

    job = await queue.dequeue(timeout=2)
    await queue.acknowledge(job)

    redis.brpoplpush.assert_awaited_once_with("analyses", "analyses:processing", timeout=2)
    redis.lrem.assert_awaited_once_with("analyses:processing", 1, job.receipt)


@pytest.mark.asyncio
async def test_redis_queue_retry_requeues_incremented_envelope() -> None:
    redis = MagicMock()
    redis.lrem = AsyncMock()
    redis.lpush = AsyncMock()
    queue = RedisAnalysisQueue(redis, "analyses")
    raw = QueueEnvelope(request=_request()).model_dump_json()
    job = QueueJob(envelope=QueueEnvelope.model_validate_json(raw), receipt=raw)
    await queue.retry(job)

    pushed = redis.lpush.await_args.args[1]
    assert QueueEnvelope.model_validate_json(pushed).attempts == 1


@pytest.mark.asyncio
async def test_redis_queue_recovers_processing_jobs() -> None:
    redis = MagicMock()
    redis.rpoplpush = AsyncMock(side_effect=["job-1", "job-2", None])
    queue = RedisAnalysisQueue(redis, "analyses")

    recovered = await queue.recover_orphaned()

    assert recovered == 2
    assert redis.rpoplpush.await_count == 3
