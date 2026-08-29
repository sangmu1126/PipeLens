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
    await queue.healthcheck()
    assert await queue.enqueue(_request()) is True
    assert await queue.enqueue(_request()) is False

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
    pipeline = MagicMock()
    pipeline.execute = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.pipeline.return_value = pipeline
    envelope = QueueEnvelope(request=_request())
    redis.brpoplpush = AsyncMock(return_value=envelope.model_dump_json())
    redis.eval = AsyncMock(return_value=1)
    queue = RedisAnalysisQueue(redis, "analyses", worker_id="worker-a")

    await queue.healthcheck()
    job = await queue.dequeue(timeout=2)
    await queue.acknowledge(job)

    redis.brpoplpush.assert_awaited_once_with(
        "analyses", "analyses:processing:worker-a", timeout=2
    )
    acknowledge_call = redis.eval.await_args
    assert acknowledge_call.args[2:] == (
        "analyses:processing:worker-a",
        "analyses:run_ids",
        job.receipt,
        "77",
    )
    pipeline.sadd.assert_called_once_with("analyses:workers", "analyses:processing:worker-a")
    pipeline.set.assert_called_once_with(
        "analyses:processing:worker-a:lease", "worker-a", ex=60
    )
    redis.ping.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_redis_queue_retry_requeues_incremented_envelope() -> None:
    redis = MagicMock()
    redis.eval = AsyncMock(return_value=1)
    queue = RedisAnalysisQueue(redis, "analyses")
    raw = QueueEnvelope(request=_request()).model_dump_json()
    job = QueueJob(envelope=QueueEnvelope.model_validate_json(raw), receipt=raw)
    await queue.retry(job)

    pushed = redis.eval.await_args.args[-1]
    assert QueueEnvelope.model_validate_json(pushed).attempts == 1
    assert redis.eval.await_args.args[2:6] == (
        queue.processing_key,
        "analyses",
        raw,
        pushed,
    )


@pytest.mark.asyncio
async def test_redis_queue_enqueues_run_once_atomically() -> None:
    redis = MagicMock()
    redis.eval = AsyncMock(side_effect=[1, 0])
    queue = RedisAnalysisQueue(redis, "analyses")

    assert await queue.enqueue(_request()) is True
    assert await queue.enqueue(_request()) is False

    first_call = redis.eval.await_args_list[0]
    assert first_call.args[2:5] == ("analyses:run_ids", "analyses", "77")


@pytest.mark.asyncio
async def test_redis_queue_recovers_processing_jobs() -> None:
    redis = MagicMock()
    redis.smembers = AsyncMock(
        return_value={"analyses:processing:worker-a", "analyses:processing:worker-b"}
    )
    redis.eval = AsyncMock(return_value=2)
    queue = RedisAnalysisQueue(redis, "analyses", worker_id="worker-a")

    recovered = await queue.recover_orphaned()

    assert recovered == 2
    redis.eval.assert_awaited_once()
    assert redis.eval.await_args.args[2:] == (
        "analyses:processing:worker-b:lease",
        "analyses:processing:worker-b",
        "analyses",
        "analyses:workers",
    )


@pytest.mark.asyncio
async def test_redis_queue_does_not_recover_its_own_processing_list() -> None:
    redis = MagicMock()
    redis.smembers = AsyncMock(return_value={"analyses:processing:worker-a"})
    redis.eval = AsyncMock()
    queue = RedisAnalysisQueue(redis, "analyses", worker_id="worker-a")

    assert await queue.recover_orphaned() == 0
    redis.eval.assert_not_awaited()
