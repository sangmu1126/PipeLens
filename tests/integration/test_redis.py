import os
import uuid

import pytest

from pipelens.models import AnalysisRequest
from pipelens.queue import RedisAnalysisQueue


def _test_redis_url() -> str:
    redis_url = os.getenv("PIPELENS_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("PIPELENS_TEST_REDIS_URL is not configured")
    return redis_url


@pytest.mark.asyncio
async def test_redis_queue_recovers_an_orphaned_job() -> None:
    redis_url = _test_redis_url()
    queue_name = f"pipelens:integration:{uuid.uuid4().hex}"
    abandoned = RedisAnalysisQueue.from_url(
        redis_url, queue_name, worker_id="abandoned", lease_seconds=30
    )
    rescuer = RedisAnalysisQueue.from_url(
        redis_url, queue_name, worker_id="rescuer", lease_seconds=30
    )
    keys = (
        queue_name,
        f"{queue_name}:run_ids",
        f"{queue_name}:workers",
        abandoned.processing_key,
        abandoned.lease_key,
        rescuer.processing_key,
        rescuer.lease_key,
    )
    try:
        await abandoned.healthcheck()
        assert await abandoned.enqueue(
            AnalysisRequest(
                run_id=91,
                repository="pipelens/integration",
                installation_id=1,
                head_sha="b" * 40,
            )
        )
        abandoned_job = await abandoned.dequeue(timeout=1)
        assert abandoned_job is not None

        await abandoned.redis.delete(abandoned.lease_key)
        assert await rescuer.recover_orphaned() == 1

        recovered_job = await rescuer.dequeue(timeout=1)
        assert recovered_job is not None
        assert recovered_job.envelope.request.run_id == 91
        await rescuer.acknowledge(recovered_job)
        assert await rescuer.size() == 0
    finally:
        await rescuer.redis.delete(*keys)
        await abandoned.close()
        await rescuer.close()
