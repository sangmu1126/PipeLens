from __future__ import annotations

import asyncio

import pytest

from ops.worker.verify_replica_recovery import DrillError, WorkTracker, parse_args, validate_args


def test_worker_drill_defaults_have_safe_lease_and_slo_order() -> None:
    args = parse_args([])

    validate_args(args)

    assert args.heartbeat_seconds < args.lease_seconds
    assert args.start_slo_seconds < args.completion_slo_seconds


def test_worker_drill_rejects_heartbeat_that_cannot_renew_lease() -> None:
    args = parse_args(["--lease-seconds", "2", "--heartbeat-seconds", "2"])

    with pytest.raises(DrillError, match="heartbeat must be shorter"):
        validate_args(args)


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
