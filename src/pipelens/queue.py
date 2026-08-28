import asyncio
import uuid
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel
from redis.asyncio import Redis

from pipelens.models import AnalysisRequest


class QueueEnvelope(BaseModel):
    request: AnalysisRequest
    attempts: int = 0


@dataclass(frozen=True)
class QueueJob:
    envelope: QueueEnvelope
    receipt: str | None = None


class AnalysisQueue(Protocol):
    async def enqueue(self, request: AnalysisRequest) -> bool: ...

    async def dequeue(self, timeout: int = 1) -> QueueJob | None: ...

    async def acknowledge(self, job: QueueJob) -> None: ...

    async def retry(self, job: QueueJob) -> None: ...

    async def heartbeat(self) -> None: ...

    async def recover_orphaned(self) -> int: ...

    async def size(self) -> int: ...

    async def close(self) -> None: ...


class InMemoryAnalysisQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[QueueEnvelope] = asyncio.Queue()
        self._run_ids: set[int] = set()

    async def enqueue(self, request: AnalysisRequest) -> bool:
        if request.run_id in self._run_ids:
            return False
        self._run_ids.add(request.run_id)
        self._queue.put_nowait(QueueEnvelope(request=request))
        return True

    async def dequeue(self, timeout: int = 1) -> QueueJob | None:
        try:
            envelope = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None
        return QueueJob(envelope=envelope)

    async def acknowledge(self, job: QueueJob) -> None:
        self._queue.task_done()
        self._run_ids.discard(job.envelope.request.run_id)

    async def retry(self, job: QueueJob) -> None:
        self._queue.task_done()
        self._queue.put_nowait(
            job.envelope.model_copy(update={"attempts": job.envelope.attempts + 1})
        )

    async def heartbeat(self) -> None:
        return None

    async def recover_orphaned(self) -> int:
        return 0

    async def size(self) -> int:
        return self._queue.qsize()

    async def close(self) -> None:
        return None


class RedisAnalysisQueue:
    _ENQUEUE_SCRIPT = """
        if redis.call('SADD', KEYS[1], ARGV[1]) == 0 then
            return 0
        end
        redis.call('LPUSH', KEYS[2], ARGV[2])
        return 1
    """
    _ACKNOWLEDGE_SCRIPT = """
        local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
        if removed > 0 then
            redis.call('SREM', KEYS[2], ARGV[2])
        end
        return removed
    """
    _RETRY_SCRIPT = """
        local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
        if removed > 0 then
            redis.call('LPUSH', KEYS[2], ARGV[2])
        end
        return removed
    """
    _RECOVER_SCRIPT = """
        if redis.call('EXISTS', KEYS[1]) == 1 then
            return 0
        end
        local recovered = 0
        while true do
            local item = redis.call('RPOP', KEYS[2])
            if not item then
                break
            end
            redis.call('LPUSH', KEYS[3], item)
            recovered = recovered + 1
        end
        redis.call('SREM', KEYS[4], KEYS[2])
        return recovered
    """

    def __init__(
        self,
        redis: Redis,
        queue_name: str,
        worker_id: str | None = None,
        lease_seconds: int = 60,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        self.redis = redis
        self.pending_key = queue_name
        self.worker_id = worker_id or uuid.uuid4().hex
        self.lease_seconds = lease_seconds
        self.workers_key = f"{queue_name}:workers"
        self.dedupe_key = f"{queue_name}:run_ids"
        self.processing_key = f"{queue_name}:processing:{self.worker_id}"
        self.lease_key = f"{self.processing_key}:lease"

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        queue_name: str,
        worker_id: str | None = None,
        lease_seconds: int = 60,
    ) -> "RedisAnalysisQueue":
        return cls(
            Redis.from_url(redis_url, decode_responses=True),
            queue_name,
            worker_id,
            lease_seconds,
        )

    async def enqueue(self, request: AnalysisRequest) -> bool:
        envelope = QueueEnvelope(request=request).model_dump_json()
        created = await self.redis.eval(
            self._ENQUEUE_SCRIPT,
            2,
            self.dedupe_key,
            self.pending_key,
            str(request.run_id),
            envelope,
        )
        return bool(created)

    async def dequeue(self, timeout: int = 1) -> QueueJob | None:
        await self.heartbeat()
        raw = await self.redis.brpoplpush(self.pending_key, self.processing_key, timeout=timeout)
        if raw is None:
            return None
        return QueueJob(envelope=QueueEnvelope.model_validate_json(raw), receipt=raw)

    async def acknowledge(self, job: QueueJob) -> None:
        if job.receipt is not None:
            await self.redis.eval(
                self._ACKNOWLEDGE_SCRIPT,
                2,
                self.processing_key,
                self.dedupe_key,
                job.receipt,
                str(job.envelope.request.run_id),
            )

    async def retry(self, job: QueueJob) -> None:
        retried = job.envelope.model_copy(update={"attempts": job.envelope.attempts + 1})
        if job.receipt is not None:
            await self.redis.eval(
                self._RETRY_SCRIPT,
                2,
                self.processing_key,
                self.pending_key,
                job.receipt,
                retried.model_dump_json(),
            )

    async def heartbeat(self) -> None:
        pipeline = self.redis.pipeline(transaction=True)
        pipeline.sadd(self.workers_key, self.processing_key)
        pipeline.set(self.lease_key, self.worker_id, ex=self.lease_seconds)
        await pipeline.execute()

    async def recover_orphaned(self) -> int:
        recovered = 0
        processing_keys = await self.redis.smembers(self.workers_key)
        for processing_key in processing_keys:
            if processing_key == self.processing_key:
                continue
            recovered += await self.redis.eval(
                self._RECOVER_SCRIPT,
                4,
                f"{processing_key}:lease",
                processing_key,
                self.pending_key,
                self.workers_key,
            )
        return recovered

    async def size(self) -> int:
        return await self.redis.llen(self.pending_key)

    async def close(self) -> None:
        await self.redis.aclose()


def create_queue(
    backend: str,
    redis_url: str,
    queue_name: str,
    *,
    worker_id: str | None = None,
    lease_seconds: int = 60,
) -> AnalysisQueue:
    if backend == "memory":
        return InMemoryAnalysisQueue()
    if backend == "redis":
        return RedisAnalysisQueue.from_url(redis_url, queue_name, worker_id, lease_seconds)
    raise ValueError(f"unsupported queue backend: {backend}")
