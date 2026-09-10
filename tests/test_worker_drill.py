from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from ops.worker.verify_replica_recovery import (
    DrillError,
    WorkTracker,
    enqueue_jobs,
    parse_args,
    percentile,
    planned_arrival_seconds,
    validate_args,
)


def test_worker_drill_defaults_have_safe_lease_and_slo_order() -> None:
    args = parse_args([])

    validate_args(args)

    assert args.heartbeat_seconds < args.lease_seconds
    assert args.start_slo_seconds < args.completion_slo_seconds


def test_worker_drill_rejects_heartbeat_that_cannot_renew_lease() -> None:
    args = parse_args(["--lease-seconds", "2", "--heartbeat-seconds", "2"])

    with pytest.raises(DrillError, match="heartbeat must be shorter"):
        validate_args(args)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--enqueue-rate-per-second", "-1"], "enqueue rate"),
        (["--jobs", "5", "--burst-size", "6"], "burst size"),
        (["--minimum-arrival-seconds", "-1"], "minimum arrival duration"),
        (["--redis-recovery-timeout-seconds", "0"], "Redis recovery timeout"),
    ],
)
def test_worker_drill_rejects_invalid_load_shape(
    arguments: list[str], message: str
) -> None:
    with pytest.raises(DrillError, match=message):
        validate_args(parse_args(arguments))


def test_worker_drill_parses_rate_shape_and_evidence_output(tmp_path: Path) -> None:
    output = tmp_path / "soak-result.json"
    args = parse_args(
        [
            "--jobs",
            "1000",
            "--enqueue-rate-per-second",
            "25",
            "--burst-size",
            "50",
            "--processing-seconds",
            "0.25",
            "--output",
            str(output),
        ]
    )

    validate_args(args)

    assert args.enqueue_rate_per_second == 25
    assert args.burst_size == 50
    assert args.processing_seconds == 0.25
    assert args.output == output


def test_planned_arrival_duration_accounts_for_recovery_probe_and_final_burst() -> None:
    short = parse_args(
        [
            "--jobs",
            "3601",
            "--enqueue-rate-per-second",
            "1",
            "--burst-size",
            "4",
        ]
    )
    exact = parse_args(
        [
            "--jobs",
            "3605",
            "--enqueue-rate-per-second",
            "1",
            "--burst-size",
            "4",
            "--minimum-arrival-seconds",
            "3600",
        ]
    )

    assert planned_arrival_seconds(short) == 3596
    assert planned_arrival_seconds(exact) == 3600
    validate_args(exact)


def test_worker_drill_rejects_profile_shorter_than_required_arrival_duration() -> None:
    args = parse_args(
        [
            "--jobs",
            "3601",
            "--enqueue-rate-per-second",
            "1",
            "--burst-size",
            "4",
            "--minimum-arrival-seconds",
            "3600",
        ]
    )

    with pytest.raises(DrillError, match=r"3596\.000s < 3600\.000s"):
        validate_args(args)


def test_nearest_rank_percentiles_are_deterministic() -> None:
    values = [0.5, 0.1, 0.4, 0.2, 0.3]

    assert percentile(values, 50) == 0.3
    assert percentile(values, 95) == 0.5
    assert percentile(values, 99) == 0.5


def test_nearest_rank_percentile_rejects_empty_samples() -> None:
    with pytest.raises(DrillError, match="requires samples"):
        percentile([], 95)


@pytest.mark.asyncio
async def test_enqueue_accepts_idempotent_duplicate_after_uncertain_redis_call() -> None:
    args = parse_args(
        [
            "--jobs",
            "1",
            "--heartbeat-seconds",
            "0.001",
            "--redis-recovery-timeout-seconds",
            "1",
        ]
    )
    producer = MagicMock()
    producer.enqueue = AsyncMock(
        side_effect=[RedisConnectionError("offline"), False]
    )
    tracker = WorkTracker(expected=1, processing_seconds=0)

    await enqueue_jobs(args, producer, tracker, stop_offset=1)

    assert producer.enqueue.await_count == 2
    assert set(tracker.enqueued_at) == {1_000_000}


@pytest.mark.asyncio
async def test_work_tracker_records_exact_processing_and_distribution() -> None:
    tracker = WorkTracker(expected=3, processing_seconds=0)
    tracker.enqueued_at = {run_id: 0 for run_id in range(3)}

    await asyncio.gather(
        tracker.process(0, "replica-1"),
        tracker.process(1, "replica-2"),
        tracker.process(2, "replica-1"),
    )

    assert tracker.completed.is_set()
    assert tracker.start_counts == {0: 1, 1: 1, 2: 1}
    assert tracker.completion_counts == {0: 1, 1: 1, 2: 1}
    assert tracker.worker_counts == {"replica-1": 2, "replica-2": 1}
