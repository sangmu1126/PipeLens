from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import generate_latest

from pipelens.metrics import Metrics
from pipelens.models import AnalysisRequest, AnalysisStatus
from pipelens.queue import InMemoryAnalysisQueue
from pipelens.worker import AnalysisWorker


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        run_id=88,
        repository="acme/widgets",
        installation_id=5,
        head_sha="abc123",
    )


@pytest.mark.asyncio
async def test_worker_retries_then_acknowledges_success() -> None:
    queue = InMemoryAnalysisQueue()
    await queue.enqueue(_request())
    pipeline = MagicMock()
    pipeline.analyze = AsyncMock(side_effect=[RuntimeError("temporary"), None])
    store = MagicMock()
    metrics = Metrics()
    worker = AnalysisWorker(pipeline, queue, store, metrics, max_attempts=3)

    assert await worker.process_next() is True
    assert await queue.size() == 1
    assert await worker.process_next() is True

    assert await queue.size() == 0
    store.update.assert_called_once_with(88, AnalysisStatus.QUEUED, error="temporary")
    output = generate_latest(metrics.registry).decode()
    assert "pipelens_queue_retries_total 1.0" in output


@pytest.mark.asyncio
async def test_worker_marks_job_failed_after_max_attempts() -> None:
    queue = InMemoryAnalysisQueue()
    await queue.enqueue(_request())
    pipeline = MagicMock()
    pipeline.analyze = AsyncMock(side_effect=RuntimeError("permanent"))
    store = MagicMock()
    metrics = Metrics()
    worker = AnalysisWorker(pipeline, queue, store, metrics, max_attempts=1)

    await worker.process_next()

    store.update.assert_called_once_with(88, AnalysisStatus.FAILED, error="permanent")
    assert await queue.size() == 0
    output = generate_latest(metrics.registry).decode()
    assert 'pipelens_analyses_total{status="failed"} 1.0' in output


@pytest.mark.asyncio
async def test_worker_renews_lease_and_records_orphan_recovery() -> None:
    queue = MagicMock()
    queue.heartbeat = AsyncMock()
    queue.recover_orphaned = AsyncMock(return_value=2)
    metrics = Metrics()
    worker = AnalysisWorker(
        MagicMock(), queue, MagicMock(), metrics, max_attempts=3, heartbeat_seconds=5
    )

    await worker._maintain_queue_once()

    queue.heartbeat.assert_awaited_once()
    queue.recover_orphaned.assert_awaited_once()
    output = generate_latest(metrics.registry).decode()
    assert "pipelens_queue_recovered_total 2.0" in output
