"""Runtime processes used by the isolated container worker soak harness."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import signal
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

import httpx
import psycopg
from prometheus_client import start_http_server
from redis.asyncio import Redis
from redis.exceptions import RedisError

from pipelens.http_retry import RetryPolicy, request_with_retry
from pipelens.metrics import Metrics
from pipelens.models import AnalysisRequest
from pipelens.queue import RedisAnalysisQueue
from pipelens.worker import AnalysisWorker


class RuntimeErrorWithContext(RuntimeError):
    """Raised when a soak runtime invariant is violated."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def nearest_rank(values: list[float], percentage: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * percentage / 100) - 1]


class ProviderState:
    def __init__(self, latencies: dict[str, float]) -> None:
        self.latencies = latencies
        self.lock = threading.Lock()
        self.request_numbers: dict[str, int] = defaultdict(int)
        self.statuses: dict[str, list[int]] = defaultdict(list)
        self.durations: dict[str, list[float]] = defaultdict(list)

    def record(self, provider: str, status: int, duration: float) -> None:
        with self.lock:
            self.statuses[provider].append(status)
            self.durations[provider].append(duration)

    def reserve(self, provider: str) -> int:
        with self.lock:
            self.request_numbers[provider] += 1
            return self.request_numbers[provider]

    def audit(self) -> dict[str, object]:
        with self.lock:
            return {
                provider: {
                    "requests": len(statuses),
                    "latency_p50_seconds": round(nearest_rank(self.durations[provider], 50), 6),
                    "latency_p95_seconds": round(nearest_rank(self.durations[provider], 95), 6),
                    "rate_limit_responses": statuses.count(HTTPStatus.TOO_MANY_REQUESTS),
                    "transient_failures": statuses.count(HTTPStatus.SERVICE_UNAVAILABLE),
                    "retry_successes": min(2, statuses.count(HTTPStatus.OK)),
                }
                for provider, statuses in sorted(self.statuses.items())
            }


def make_provider_handler(state: ProviderState) -> type[BaseHTTPRequestHandler]:
    class ProviderHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if self.path == "/audit":
                self._send_json(HTTPStatus.OK, state.audit())
                return
            provider = urlparse(self.path).path.removeprefix("/")
            if provider not in state.latencies:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown provider"})
                return
            started = time.monotonic()
            request_number = state.reserve(provider)
            time.sleep(state.latencies[provider])
            if request_number == 1:
                status = HTTPStatus.TOO_MANY_REQUESTS
            elif request_number == 2:
                status = HTTPStatus.SERVICE_UNAVAILABLE
            else:
                status = HTTPStatus.OK
            state.record(provider, status, time.monotonic() - started)
            headers = {"Retry-After": "0"} if status == HTTPStatus.TOO_MANY_REQUESTS else {}
            self._send_json(status, {"provider": provider}, headers)

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send_json(
            self,
            status: int,
            body: dict[str, object],
            headers: dict[str, str] | None = None,
        ) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)

    return ProviderHandler


def run_provider(args: argparse.Namespace) -> int:
    state = ProviderState({"github": args.github_latency, "llm": args.llm_latency})
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_provider_handler(state))
    server.serve_forever()
    return 0


class RedisTracker:
    _START_SCRIPT = """
        redis.call('HINCRBY', KEYS[1], ARGV[1], 1)
        redis.call('HSETNX', KEYS[2], ARGV[1], ARGV[2])
        redis.call('HSET', KEYS[3], ARGV[1], ARGV[2])
        redis.call('HINCRBY', KEYS[4], ARGV[3], 1)
        return 1
    """
    _COMPLETE_SCRIPT = """
        redis.call('HINCRBY', KEYS[1], ARGV[1], 1)
        redis.call('HSETNX', KEYS[2], ARGV[1], ARGV[2])
        return 1
    """

    def __init__(self, redis: Redis, prefix: str) -> None:
        self.redis = redis
        self.prefix = prefix
        self.enqueued = f"{prefix}:enqueued"
        self.starts = f"{prefix}:starts"
        self.first_start = f"{prefix}:first_start"
        self.last_start = f"{prefix}:last_start"
        self.completions = f"{prefix}:completions"
        self.first_completion = f"{prefix}:first_completion"
        self.worker_counts = f"{prefix}:worker_counts"
        self.victim_ready = f"{prefix}:victim_ready"

    async def retry(self, operation: Any, *args: object) -> Any:
        while True:
            try:
                return await operation(*args)
            except RedisError:
                await asyncio.sleep(0.1)

    async def record_start(self, run_id: int, worker_id: str) -> None:
        timestamp = time.time()
        await self.retry(
            self.redis.eval,
            self._START_SCRIPT,
            4,
            self.starts,
            self.first_start,
            self.last_start,
            self.worker_counts,
            str(run_id),
            str(timestamp),
            worker_id,
        )

    async def record_completion(self, run_id: int) -> None:
        await self.retry(
            self.redis.eval,
            self._COMPLETE_SCRIPT,
            2,
            self.completions,
            self.first_completion,
            str(run_id),
            str(time.time()),
        )


class ContainerPipeline:
    def __init__(
        self,
        tracker: RedisTracker,
        worker_id: str,
        provider_url: str,
        victim_run_id: int,
        victim_hold_seconds: float,
    ) -> None:
        self.tracker = tracker
        self.worker_id = worker_id
        self.provider_url = provider_url.rstrip("/")
        self.victim_run_id = victim_run_id
        self.victim_hold_seconds = victim_hold_seconds
        self.client = httpx.AsyncClient(timeout=30)

    async def analyze(self, request: AnalysisRequest) -> None:
        await self.tracker.record_start(request.run_id, self.worker_id)
        if request.run_id == self.victim_run_id and self.worker_id == "worker-1":
            await self.tracker.retry(self.tracker.redis.set, self.tracker.victim_ready, utc_now())
            await asyncio.sleep(self.victim_hold_seconds)
        for provider in ("github", "llm"):
            response = await request_with_retry(
                self.client,
                "GET",
                f"{self.provider_url}/{provider}",
                policy=RetryPolicy(
                    max_attempts=4,
                    base_delay_seconds=0.01,
                    max_delay_seconds=0.05,
                    jitter_ratio=0,
                ),
            )
            response.raise_for_status()
        await self.tracker.record_completion(request.run_id)


class NoopStore:
    def update(self, *_args: object, **_kwargs: object) -> None:
        return


def open_database_pool(database_url: str, worker_id: str, size: int) -> list[Any]:
    connections = []
    deadline = time.monotonic() + 30
    while len(connections) < size:
        try:
            connection = psycopg.connect(
                database_url,
                application_name=f"pipelens-soak-{worker_id}",
                connect_timeout=2,
            )
        except psycopg.OperationalError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
            continue
        connections.append(connection)
    return connections


async def run_worker(args: argparse.Namespace) -> int:
    pool = open_database_pool(args.database_url, args.worker_id, args.postgres_pool_size)
    redis = Redis.from_url(args.redis_url, decode_responses=True)
    tracker = RedisTracker(redis, args.tracker_prefix)
    queue = RedisAnalysisQueue(
        redis,
        args.queue_name,
        worker_id=args.worker_id,
        lease_seconds=args.lease_seconds,
    )
    metrics = Metrics()
    start_http_server(args.metrics_port, registry=metrics.registry)
    pipeline = ContainerPipeline(
        tracker,
        args.worker_id,
        args.provider_url,
        args.victim_run_id,
        args.victim_hold_seconds,
    )
    worker = AnalysisWorker(
        pipeline,  # type: ignore[arg-type]
        queue,
        NoopStore(),  # type: ignore[arg-type]
        metrics,
        max_attempts=4,
        heartbeat_seconds=args.heartbeat_seconds,
    )
    try:
        await worker.run()
    finally:
        await pipeline.client.aclose()
        await queue.close()
        for connection in pool:
            connection.close()
    return 0


def analysis_request(run_id: int) -> AnalysisRequest:
    return AnalysisRequest(
        run_id=run_id,
        repository="pipelens/container-soak",
        installation_id=1,
        head_sha=f"{run_id:040x}"[-40:],
    )


async def enqueue_with_retry(queue: RedisAnalysisQueue, request: AnalysisRequest) -> None:
    uncertain = False
    while True:
        try:
            created = await queue.enqueue(request)
        except RedisError:
            uncertain = True
            await asyncio.sleep(0.1)
            continue
        if not created and not uncertain:
            raise RuntimeErrorWithContext(f"duplicate synthetic run ID: {request.run_id}")
        return


async def seed_victim(args: argparse.Namespace) -> int:
    queue = RedisAnalysisQueue.from_url(
        args.redis_url, args.queue_name, worker_id="producer", lease_seconds=args.lease_seconds
    )
    tracker = RedisTracker(queue.redis, args.tracker_prefix)
    try:
        await tracker.retry(queue.redis.hset, tracker.enqueued, args.victim_run_id, time.time())
        await enqueue_with_retry(queue, analysis_request(args.victim_run_id))
    finally:
        await queue.close()
    return 0


def float_hash(values: dict[str, str]) -> dict[int, float]:
    return {int(key): float(value) for key, value in values.items()}


def int_hash(values: dict[str, str]) -> dict[int, int]:
    return {int(key): int(value) for key, value in values.items()}


async def processing_count(tracker: RedisTracker, keys: set[str]) -> int:
    count = 0
    for key in keys:
        count += int(await tracker.retry(tracker.redis.llen, key))
    return count


async def run_coordinator(args: argparse.Namespace) -> dict[str, object]:
    queue = RedisAnalysisQueue.from_url(
        args.redis_url, args.queue_name, worker_id="producer", lease_seconds=args.lease_seconds
    )
    tracker = RedisTracker(queue.redis, args.tracker_prefix)
    started = time.monotonic()
    try:
        run_ids = range(args.victim_run_id + 1, args.victim_run_id + args.jobs)
        for position, run_id in enumerate(run_ids, start=1):
            await tracker.retry(queue.redis.hset, tracker.enqueued, run_id, time.time())
            await enqueue_with_retry(queue, analysis_request(run_id))
            if position % args.burst_size == 0 and position < args.jobs - 1:
                target = started + position / args.arrival_rate
                await asyncio.sleep(max(0, target - time.monotonic()))

        deadline = time.monotonic() + args.completion_timeout
        while int(await tracker.retry(queue.redis.hlen, tracker.first_completion)) < args.jobs:
            if time.monotonic() >= deadline:
                raise RuntimeErrorWithContext("workload did not complete before its timeout")
            await asyncio.sleep(0.1)

        while True:
            processing_keys = await tracker.retry(queue.redis.smembers, queue.workers_key)
            pending = int(await tracker.retry(queue.size))
            processing = await processing_count(tracker, processing_keys)
            deduplicated = int(await tracker.retry(queue.redis.scard, queue.dedupe_key))
            if pending == 0 and processing == 0 and deduplicated == 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeErrorWithContext("queue did not drain before its timeout")
            await asyncio.sleep(0.05)

        enqueued = float_hash(await tracker.retry(queue.redis.hgetall, tracker.enqueued))
        first_starts = float_hash(await tracker.retry(queue.redis.hgetall, tracker.first_start))
        last_starts = float_hash(await tracker.retry(queue.redis.hgetall, tracker.last_start))
        completions = float_hash(await tracker.retry(queue.redis.hgetall, tracker.first_completion))
        completion_counts = int_hash(await tracker.retry(queue.redis.hgetall, tracker.completions))
        start_counts = int_hash(await tracker.retry(queue.redis.hgetall, tracker.starts))
        worker_counts = {
            key: int(value)
            for key, value in (
                await tracker.retry(queue.redis.hgetall, tracker.worker_counts)
            ).items()
        }
        expected = set(enqueued)
        lost = sorted(expected - completions.keys())
        duplicate_completions = sum(max(0, count - 1) for count in completion_counts.values())
        start_latencies = [first_starts[item] - enqueued[item] for item in expected]
        completion_latencies = [completions[item] - enqueued[item] for item in expected]
        pending = int(await tracker.retry(queue.size))
        processing_keys = await tracker.retry(queue.redis.smembers, queue.workers_key)
        processing = await processing_count(tracker, processing_keys)
        observed = max(completions.values()) - min(enqueued.values())
        return {
            "schema_version": 1,
            "started_at": datetime.fromtimestamp(min(enqueued.values()), UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "completed_at": datetime.fromtimestamp(max(completions.values()), UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "observed_duration_seconds": round(observed, 6),
            "jobs": args.jobs,
            "completed_jobs": len(completions),
            "duplicate_completions": duplicate_completions,
            "lost_jobs": len(lost),
            "queue_drained": pending == 0 and processing == 0,
            "exactly_once": not lost and duplicate_completions == 0,
            "worker_counts": worker_counts,
            "start_counts": {
                "retried_jobs": sum(count > 1 for count in start_counts.values()),
                "maximum": max(start_counts.values()),
            },
            "latency_seconds": {
                "start_p50": round(nearest_rank(start_latencies, 50), 6),
                "start_p95": round(nearest_rank(start_latencies, 95), 6),
                "start_p99": round(nearest_rank(start_latencies, 99), 6),
                "completion_p50": round(nearest_rank(completion_latencies, 50), 6),
                "completion_p95": round(nearest_rank(completion_latencies, 95), 6),
                "completion_p99": round(nearest_rank(completion_latencies, 99), 6),
                "victim_recovery": round(
                    last_starts[args.victim_run_id] - first_starts[args.victim_run_id], 6
                ),
            },
            "slo_attainment_percent": {
                "start": round(
                    100 * sum(value <= args.start_slo for value in start_latencies) / args.jobs,
                    6,
                ),
                "completion": round(
                    100
                    * sum(value <= args.completion_slo for value in completion_latencies)
                    / args.jobs,
                    6,
                ),
            },
            "throughput_jobs_per_second": round(args.jobs / observed, 6),
        }
    finally:
        await queue.close()


def add_shared_queue_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--queue-name", required=True)
    parser.add_argument("--tracker-prefix", required=True)
    parser.add_argument("--lease-seconds", type=int, required=True)
    parser.add_argument("--victim-run-id", type=int, default=1_000_000)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    provider = subparsers.add_parser("provider")
    provider.add_argument("--port", type=int, default=8080)
    provider.add_argument("--github-latency", type=float, required=True)
    provider.add_argument("--llm-latency", type=float, required=True)

    worker = subparsers.add_parser("worker")
    add_shared_queue_arguments(worker)
    worker.add_argument("--worker-id", required=True)
    worker.add_argument("--database-url", required=True)
    worker.add_argument("--postgres-pool-size", type=int, required=True)
    worker.add_argument("--provider-url", required=True)
    worker.add_argument("--heartbeat-seconds", type=float, required=True)
    worker.add_argument("--victim-hold-seconds", type=float, required=True)
    worker.add_argument("--metrics-port", type=int, default=8001)

    seed = subparsers.add_parser("seed-victim")
    add_shared_queue_arguments(seed)

    coordinator = subparsers.add_parser("coordinator")
    add_shared_queue_arguments(coordinator)
    coordinator.add_argument("--jobs", type=int, required=True)
    coordinator.add_argument("--arrival-rate", type=float, required=True)
    coordinator.add_argument("--burst-size", type=int, required=True)
    coordinator.add_argument("--completion-timeout", type=float, required=True)
    coordinator.add_argument("--start-slo", type=float, default=60)
    coordinator.add_argument("--completion-slo", type=float, default=120)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "provider":
        return run_provider(args)
    if args.command == "worker":
        signal.signal(signal.SIGTERM, lambda *_args: raise_system_exit())
        return asyncio.run(run_worker(args))
    if args.command == "seed-victim":
        return asyncio.run(seed_victim(args))
    result = asyncio.run(run_coordinator(args))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["exactly_once"] and result["queue_drained"] else 1


def raise_system_exit() -> None:
    raise SystemExit(0)


if __name__ == "__main__":
    raise SystemExit(main())
