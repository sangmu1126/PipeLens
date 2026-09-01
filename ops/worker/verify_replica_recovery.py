"""Run a synthetic Redis worker replica load and lease-recovery drill."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from typing import Any

from pipelens.metrics import Metrics
from pipelens.models import AnalysisRequest
from pipelens.queue import RedisAnalysisQueue
from pipelens.worker import AnalysisWorker


class DrillError(RuntimeError):
    """Raised when the synthetic worker drill violates an invariant or SLO."""


@dataclass
class WorkTracker:
    expected: int
    processing_seconds: float
    enqueued_at: dict[int, float] = field(default_factory=dict)
    started_at: dict[int, float] = field(default_factory=dict)
    completed_at: dict[int, float] = field(default_factory=dict)
    start_counts: Counter[int] = field(default_factory=Counter)
    completion_counts: Counter[int] = field(default_factory=Counter)
    worker_counts: Counter[str] = field(default_factory=Counter)
    completed: asyncio.Event = field(default_factory=asyncio.Event)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def process(self, run_id: int, worker_id: str) -> None:
        async with self.lock:
            self.start_counts[run_id] += 1
            self.started_at.setdefault(run_id, time.monotonic())
            self.worker_counts[worker_id] += 1
        await asyncio.sleep(self.processing_seconds)
        async with self.lock:
            self.completion_counts[run_id] += 1
            self.completed_at.setdefault(run_id, time.monotonic())
            if len(self.completed_at) == self.expected:
                self.completed.set()


class SyntheticPipeline:
    def __init__(self, tracker: WorkTracker, worker_id: str) -> None:
        self.tracker = tracker
        self.worker_id = worker_id

    async def analyze(self, request: AnalysisRequest) -> None:
        await self.tracker.process(request.run_id, self.worker_id)


class NoFailureStore:
    def update(self, *_args: Any, **_kwargs: Any) -> None:
        raise DrillError("synthetic pipeline unexpectedly entered the worker failure path")


def counter_value(metrics: Metrics, sample_name: str) -> float:
    return sum(
        sample.value
        for metric in metrics.registry.collect()
        for sample in metric.samples
        if sample.name == sample_name
    )


def percentile(values: list[float], percentage: int) -> float:
    """Return a nearest-rank percentile for a non-empty sample."""
    if not values or not 1 <= percentage <= 100:
        raise DrillError("percentile requires samples and a percentage from 1 to 100")
    ordered = sorted(values)
    return ordered[ceil(len(ordered) * percentage / 100) - 1]


def validate_args(args: argparse.Namespace) -> None:
    positive_values = {
        "jobs": args.jobs,
        "replicas": args.replicas,
        "lease_seconds": args.lease_seconds,
        "heartbeat_seconds": args.heartbeat_seconds,
        "processing_seconds": args.processing_seconds,
        "start_slo_seconds": args.start_slo_seconds,
        "completion_slo_seconds": args.completion_slo_seconds,
        "recovery_grace_seconds": args.recovery_grace_seconds,
    }
    invalid = [name for name, value in positive_values.items() if value <= 0]
    if invalid:
        raise DrillError(f"arguments must be positive: {', '.join(invalid)}")
    if args.heartbeat_seconds >= args.lease_seconds:
        raise DrillError("heartbeat must be shorter than the worker lease")
    if args.completion_slo_seconds < args.start_slo_seconds:
        raise DrillError("completion SLO must not be shorter than start SLO")
    if args.enqueue_rate_per_second < 0:
        raise DrillError("enqueue rate must not be negative")
    if args.burst_size < 0 or args.burst_size > args.jobs:
        raise DrillError("burst size must be zero or no greater than jobs")


async def wait_until_acknowledged(queue: RedisAnalysisQueue, timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while await queue.redis.scard(queue.dedupe_key):
            await asyncio.sleep(0.01)


async def enqueue_jobs(
    args: argparse.Namespace,
    producer: RedisAnalysisQueue,
    tracker: WorkTracker,
    start_offset: int = 0,
    stop_offset: int | None = None,
) -> float:
    """Enqueue a burst or rate-shaped workload and return enqueue duration."""
    started = time.monotonic()
    burst_size = args.burst_size or (1 if args.enqueue_rate_per_second else args.jobs)
    for position, offset in enumerate(
        range(start_offset, stop_offset if stop_offset is not None else args.jobs), start=1
    ):
        run_id = 1_000_000 + offset
        tracker.enqueued_at[run_id] = time.monotonic()
        created = await producer.enqueue(
            AnalysisRequest(
                run_id=run_id,
                repository="pipelens/replica-drill",
                installation_id=1,
                head_sha=f"{offset:040x}",
            )
        )
        if not created:
            raise DrillError(f"duplicate enqueue for synthetic run {run_id}")
        if (
            args.enqueue_rate_per_second
            and stop_offset is None
            and offset + 1 < args.jobs
            and position % burst_size == 0
        ):
            target = started + position / args.enqueue_rate_per_second
            await asyncio.sleep(max(0, target - time.monotonic()))
    return time.monotonic() - started


async def run_drill(args: argparse.Namespace) -> dict[str, object]:
    validate_args(args)
    checked_at = datetime.now(UTC)
    queue_name = f"pipelens:replica-drill:{uuid.uuid4().hex}"
    producer = RedisAnalysisQueue.from_url(
        args.redis_url, queue_name, worker_id="producer", lease_seconds=args.lease_seconds
    )
    abandoned = RedisAnalysisQueue.from_url(
        args.redis_url, queue_name, worker_id="abandoned", lease_seconds=args.lease_seconds
    )
    replica_queues = [
        RedisAnalysisQueue.from_url(
            args.redis_url,
            queue_name,
            worker_id=f"replica-{index + 1}",
            lease_seconds=args.lease_seconds,
        )
        for index in range(args.replicas)
    ]
    tracker = WorkTracker(args.jobs, args.processing_seconds)
    metrics = [Metrics() for _ in replica_queues]
    workers = [
        AnalysisWorker(
            SyntheticPipeline(tracker, queue.worker_id),  # type: ignore[arg-type]
            queue,
            NoFailureStore(),  # type: ignore[arg-type]
            worker_metrics,
            max_attempts=1,
            heartbeat_seconds=args.heartbeat_seconds,
        )
        for queue, worker_metrics in zip(replica_queues, metrics, strict=True)
    ]
    all_queues = [producer, abandoned, *replica_queues]
    keys = {
        producer.pending_key,
        producer.dedupe_key,
        producer.workers_key,
        *(queue.processing_key for queue in all_queues),
        *(queue.lease_key for queue in all_queues),
    }

    abandoned_run_id: int | None = None
    redis_connected = False
    try:
        await producer.healthcheck()
        redis_connected = True
        enqueue_started = time.monotonic()
        await enqueue_jobs(args, producer, tracker, stop_offset=1)

        abandoned_job = await abandoned.dequeue(timeout=1)
        if abandoned_job is None:
            raise DrillError("abandoned worker could not claim a job")
        abandoned_run_id = abandoned_job.envelope.request.run_id

        for worker in workers:
            await worker.start()
        if args.jobs > 1:
            await enqueue_jobs(args, producer, tracker, start_offset=1)
        enqueue_seconds = time.monotonic() - enqueue_started
        async with asyncio.timeout(args.completion_slo_seconds):
            await tracker.completed.wait()
        await wait_until_acknowledged(producer)

        expected_ids = set(tracker.enqueued_at)
        if set(tracker.started_at) != expected_ids or set(tracker.completed_at) != expected_ids:
            raise DrillError("not every enqueued job reached start and completion")
        duplicates = sorted(
            run_id
            for run_id in expected_ids
            if tracker.start_counts[run_id] != 1 or tracker.completion_counts[run_id] != 1
        )
        if duplicates:
            raise DrillError(f"jobs were not processed exactly once: {duplicates[:10]}")
        idle_replicas = sorted(
            queue.worker_id
            for queue in replica_queues
            if not tracker.worker_counts[queue.worker_id]
        )
        if idle_replicas:
            raise DrillError(f"replicas processed no jobs: {idle_replicas}")

        start_latencies = {
            run_id: tracker.started_at[run_id] - enqueued_at
            for run_id, enqueued_at in tracker.enqueued_at.items()
        }
        completion_latencies = {
            run_id: tracker.completed_at[run_id] - enqueued_at
            for run_id, enqueued_at in tracker.enqueued_at.items()
        }
        max_start = max(start_latencies.values())
        max_completion = max(completion_latencies.values())
        recovery_latency = start_latencies[abandoned_run_id]
        if max_start > args.start_slo_seconds:
            raise DrillError(f"start SLO breached: {max_start:.3f}s")
        if max_completion > args.completion_slo_seconds:
            raise DrillError(f"completion SLO breached: {max_completion:.3f}s")
        recovery_limit = args.lease_seconds + args.recovery_grace_seconds
        if recovery_latency > recovery_limit:
            raise DrillError(
                f"orphan recovery exceeded lease plus grace: {recovery_latency:.3f}s"
            )

        recovered = sum(
            counter_value(worker_metrics, "pipelens_queue_recovered_total")
            for worker_metrics in metrics
        )
        if recovered != 1:
            raise DrillError(f"expected one recovered job, observed {recovered:g}")
        if await producer.size() != 0:
            raise DrillError("pending queue was not fully drained")

        start_samples = list(start_latencies.values())
        completion_samples = list(completion_latencies.values())
        observed_seconds = max(tracker.completed_at.values()) - min(tracker.enqueued_at.values())
        start_attainment = sum(
            latency <= args.start_slo_seconds for latency in start_samples
        ) / args.jobs
        completion_attainment = sum(
            latency <= args.completion_slo_seconds for latency in completion_samples
        ) / args.jobs

        return {
            "schema_version": 1,
            "checked_at": checked_at.isoformat(),
            "jobs": args.jobs,
            "replicas": args.replicas,
            "enqueue_rate_per_second": args.enqueue_rate_per_second,
            "burst_size": args.burst_size or (1 if args.enqueue_rate_per_second else args.jobs),
            "synthetic_processing_seconds": args.processing_seconds,
            "enqueue_seconds": round(enqueue_seconds, 3),
            "observed_seconds": round(observed_seconds, 3),
            "throughput_jobs_per_second": round(args.jobs / observed_seconds, 3),
            "processed_per_replica": dict(sorted(tracker.worker_counts.items())),
            "recovered_jobs": int(recovered),
            "max_start_seconds": round(max_start, 3),
            "max_completion_seconds": round(max_completion, 3),
            "orphan_recovery_seconds": round(recovery_latency, 3),
            "start_latency_seconds": {
                f"p{rank}": round(percentile(start_samples, rank), 3)
                for rank in (50, 95, 99)
            },
            "completion_latency_seconds": {
                f"p{rank}": round(percentile(completion_samples, rank), 3)
                for rank in (50, 95, 99)
            },
            "start_slo_seconds": args.start_slo_seconds,
            "completion_slo_seconds": args.completion_slo_seconds,
            "start_slo_attainment_percent": round(start_attainment * 100, 3),
            "completion_slo_attainment_percent": round(completion_attainment * 100, 3),
            "exactly_once": True,
            "queue_drained": True,
        }
    except TimeoutError as error:
        raise DrillError(
            "worker replicas did not drain the queue before the completion SLO"
        ) from error
    finally:
        await asyncio.gather(*(worker.stop() for worker in workers), return_exceptions=True)
        try:
            if redis_connected:
                await producer.redis.delete(*keys)
        finally:
            await asyncio.gather(*(queue.close() for queue in all_queues), return_exceptions=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--jobs", type=int, default=200)
    parser.add_argument("--replicas", type=int, default=4)
    parser.add_argument("--lease-seconds", type=int, default=2)
    parser.add_argument("--heartbeat-seconds", type=float, default=0.5)
    parser.add_argument("--processing-seconds", type=float, default=0.01)
    parser.add_argument("--enqueue-rate-per-second", type=float, default=0)
    parser.add_argument("--burst-size", type=int, default=0)
    parser.add_argument("--start-slo-seconds", type=float, default=60)
    parser.add_argument("--completion-slo-seconds", type=float, default=120)
    parser.add_argument("--recovery-grace-seconds", type=float, default=5)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = asyncio.run(run_drill(args))
    except DrillError as error:
        print(f"worker replica drill failed: {error}")
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        try:
            args.output.write_text(rendered, encoding="utf-8")
        except OSError as error:
            print(f"worker replica drill could not write evidence: {error}")
            return 1
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
