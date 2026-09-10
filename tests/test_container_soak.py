from argparse import Namespace
from pathlib import Path

import pytest

import ops.worker.run_container_soak as container_soak
from ops.worker.container_runtime import ProviderState, nearest_rank
from ops.worker.run_container_soak import (
    PROFILES,
    SoakError,
    aggregate_resources,
    artifact_scan,
    execute,
    metric_total,
    provider_audit,
)


def test_profiles_have_expected_arrival_windows() -> None:
    assert PROFILES["smoke"].planned_duration == 1
    assert PROFILES["launch"].planned_duration == 3600


def test_nearest_rank_is_deterministic() -> None:
    values = [0.5, 0.1, 0.4, 0.2, 0.3]

    assert nearest_rank(values, 50) == 0.3
    assert nearest_rank(values, 95) == 0.5


def test_provider_audit_counts_injected_failures() -> None:
    state = ProviderState({"github": 0.1})
    assert [state.reserve("github") for _ in range(3)] == [1, 2, 3]
    state.record("github", 429, 0.1)
    state.record("github", 503, 0.2)
    state.record("github", 200, 0.3)
    state.record("github", 200, 0.4)

    assert state.audit()["github"] == {
        "requests": 4,
        "latency_p50_seconds": 0.2,
        "latency_p95_seconds": 0.4,
        "rate_limit_responses": 1,
        "transient_failures": 1,
        "retry_successes": 2,
    }


def test_provider_audit_rejects_non_object_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_soak, "exec_output", lambda *_args: "[]")

    with pytest.raises(SoakError, match="non-object"):
        provider_audit("provider")


def test_metric_total_combines_replicas_and_ignores_metadata() -> None:
    payloads = [
        "# HELP pipelens_queue_reconnections_total test\n"
        'pipelens_queue_reconnections_total{phase="processing"} 1.0\n',
        'pipelens_queue_reconnections_total{phase="maintenance"} 2.0\n',
    ]

    assert metric_total(payloads, "pipelens_queue_reconnections_total") == 3


def test_resource_aggregation_uses_each_peak() -> None:
    samples = [
        {
            "captured_at": "2026-09-09T00:00:00Z",
            "worker_cpu_peak_percent": 2,
            "worker_memory_peak_percent": 10,
            "postgres_pool_connections": 20,
            "postgres_total_connections": 25,
            "redis_memory_percent": 1,
        },
        {
            "captured_at": "2026-09-09T00:00:01Z",
            "worker_cpu_peak_percent": 3,
            "worker_memory_peak_percent": 9,
            "postgres_pool_connections": 19,
            "postgres_total_connections": 24,
            "redis_memory_percent": 2,
        },
    ]

    assert aggregate_resources(samples) == {
        "captured_at": "2026-09-09T00:00:01Z",
        "worker_cpu_peak_percent": 3,
        "worker_memory_peak_percent": 10,
        "postgres_pool_peak_connections": 20,
        "postgres_total_peak_connections": 25,
        "redis_memory_peak_percent": 2,
    }


def test_artifact_scan_detects_forbidden_endpoint_and_secret_names(tmp_path: Path) -> None:
    clean = tmp_path / "clean.json"
    dirty = tmp_path / "dirty.json"
    clean.write_text('{"status":"ok"}', encoding="utf-8")
    dirty.write_text('{"password":"x","endpoint":"http://internal"}', encoding="utf-8")

    assert artifact_scan([clean]) == 0
    assert artifact_scan([dirty]) == 2


def test_invalid_run_id_is_rejected_before_docker_access(tmp_path: Path) -> None:
    args = Namespace(
        profile="smoke",
        run_id="unsafe/identifier",
        output_dir=tmp_path / "output",
        keep=False,
    )

    with pytest.raises(SoakError, match="run ID"):
        execute(args)
    assert not args.output_dir.exists()
