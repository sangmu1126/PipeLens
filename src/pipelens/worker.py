import asyncio
import logging
import time
from contextlib import suppress

from prometheus_client import start_http_server
from redis.exceptions import RedisError

from pipelens.bootstrap import create_runtime
from pipelens.config import Settings, get_settings
from pipelens.metrics import Metrics
from pipelens.models import AnalysisStatus
from pipelens.pipeline import AnalysisPipeline
from pipelens.queue import AnalysisQueue
from pipelens.store import AnalysisStore

logger = logging.getLogger(__name__)


class AnalysisWorker:
    def __init__(
        self,
        pipeline: AnalysisPipeline,
        queue: AnalysisQueue,
        store: AnalysisStore,
        metrics: Metrics,
        max_attempts: int,
        heartbeat_seconds: float = 15,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        self.pipeline = pipeline
        self.queue = queue
        self.store = store
        self.metrics = metrics
        self.max_attempts = max_attempts
        self.heartbeat_seconds = heartbeat_seconds
        self._task: asyncio.Task[None] | None = None
        self._queue_failure_started_at: dict[str, float] = {}

    async def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="pipelens-analysis-worker")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def run(self) -> None:
        while True:
            try:
                await self._maintain_queue_once()
            except RedisError:
                self._record_queue_error("startup")
                logger.exception(
                    "queue unavailable during worker startup; retrying in %.1fs",
                    self.heartbeat_seconds,
                )
                await asyncio.sleep(self.heartbeat_seconds)
            else:
                self._record_queue_success("startup")
                break
        maintenance_task = asyncio.create_task(
            self._maintain_queue(), name="pipelens-queue-maintenance"
        )
        try:
            while True:
                try:
                    await self.process_next()
                except RedisError:
                    self._record_queue_error("processing")
                    logger.exception(
                        "queue operation failed; retrying in %.1fs",
                        self.heartbeat_seconds,
                    )
                    await asyncio.sleep(self.heartbeat_seconds)
                else:
                    self._record_queue_success("processing")
        finally:
            maintenance_task.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance_task

    async def _maintain_queue(self) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            try:
                await self._maintain_queue_once()
            except RedisError:
                self._record_queue_error("maintenance")
                logger.exception("queue lease maintenance failed")
            except Exception:
                logger.exception("queue lease maintenance failed")
            else:
                self._record_queue_success("maintenance")

    def _record_queue_error(self, phase: str) -> None:
        self.metrics.queue_connection_errors.labels(phase=phase).inc()
        self._queue_failure_started_at.setdefault(phase, time.monotonic())

    def _record_queue_success(self, phase: str) -> None:
        started_at = self._queue_failure_started_at.pop(phase, None)
        if started_at is None:
            return
        self.metrics.queue_reconnections.labels(phase=phase).inc()
        self.metrics.queue_recovery_duration.labels(phase=phase).observe(
            time.monotonic() - started_at
        )

    async def _maintain_queue_once(self) -> None:
        await self.queue.heartbeat()
        recovered = await self.queue.recover_orphaned()
        if recovered:
            logger.warning("recovered %s orphaned analysis jobs", recovered)
            self.metrics.queue_recovered.inc(recovered)

    async def process_next(self, timeout: int = 1) -> bool:
        job = await self.queue.dequeue(timeout=timeout)
        if job is None:
            self.metrics.queue_depth.set(await self.queue.size())
            return False
        request = job.envelope.request
        self.metrics.queue_depth.set(await self.queue.size())
        try:
            await self.pipeline.analyze(request)
        except Exception as exc:
            attempt = job.envelope.attempts + 1
            if attempt < self.max_attempts:
                logger.warning(
                    "analysis attempt %s/%s failed for run %s; retrying",
                    attempt,
                    self.max_attempts,
                    request.run_id,
                    exc_info=True,
                )
                self.store.update(request.run_id, AnalysisStatus.QUEUED, error=str(exc))
                await self.queue.retry(job)
                self.metrics.queue_retries.inc()
            else:
                logger.exception("analysis failed permanently for run %s", request.run_id)
                self.store.update(request.run_id, AnalysisStatus.FAILED, error=str(exc))
                await self.queue.acknowledge(job)
                self.metrics.analyses.labels(status="failed").inc()
        else:
            await self.queue.acknowledge(job)
        self.metrics.queue_depth.set(await self.queue.size())
        return True


async def run_worker(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    runtime = create_runtime(settings)
    runtime.store.initialize()
    start_http_server(settings.worker_metrics_port, registry=runtime.metrics.registry)
    worker = AnalysisWorker(
        runtime.pipeline,
        runtime.queue,
        runtime.store,
        runtime.metrics,
        settings.worker_max_attempts,
        settings.worker_heartbeat_seconds,
    )
    try:
        await worker.run()
    finally:
        await runtime.queue.close()
        runtime.store.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
