from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ops.worker.verify_soak_evidence import compile_evidence, load_observation, main

EXAMPLE_PATH = Path("ops/worker/soak-observation.example.json")
CHECKED_AT = datetime(2026, 9, 2, tzinfo=UTC)


def valid_observation() -> dict[str, Any]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def compile_valid(observation: dict[str, Any] | None = None) -> dict[str, Any]:
    return compile_evidence(
        observation or valid_observation(),
        "a" * 64,
        min_duration_seconds=3600,
        min_slo_attainment_percent=99,
        max_resource_utilization_percent=90,
        max_fault_recovery_seconds=120,
        checked_at=CHECKED_AT,
    )


def test_checked_in_example_passes_all_checks() -> None:
    observation, digest = load_observation(EXAMPLE_PATH)
    evidence = compile_evidence(
        observation,
        digest,
        min_duration_seconds=3600,
        min_slo_attainment_percent=99,
        max_resource_utilization_percent=90,
        max_fault_recovery_seconds=120,
        checked_at=CHECKED_AT,
    )

    assert evidence["passed"] is True
    assert all(evidence["checks"].values())
    assert evidence["soak_window"]["observed_duration_seconds"] == 7200
    assert evidence["fault_injection"]["network_interruption"]["recovery_seconds"] == 75


def test_owner_is_redacted_to_documented_boolean() -> None:
    observation = valid_observation()
    owner = observation["capacity_recommendation"]["owner"]

    evidence = compile_valid(observation)

    assert owner not in json.dumps(evidence)
    assert evidence["capacity_recommendation"]["owner_documented"] is True


def test_short_soak_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["started_at"] = "2025-09-02T03:30:00Z"
    observation["load_profile"]["planned_duration_seconds"] = 1800
    observation["fault_injection"]["worker_termination"]["injected_at"] = (
        "2025-09-02T03:31:00Z"
    )
    observation["fault_injection"]["worker_termination"]["recovered_at"] = (
        "2025-09-02T03:31:45Z"
    )
    observation["fault_injection"]["expired_lease"]["injected_at"] = (
        "2025-09-02T03:35:00Z"
    )
    observation["fault_injection"]["expired_lease"]["recovered_at"] = (
        "2025-09-02T03:36:00Z"
    )

    evidence = compile_valid(observation)

    assert evidence["checks"]["production_duration"] is False


def test_postgres_pool_budget_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["resource_limits"]["postgres_pool_size_each"] = 20

    evidence = compile_valid(observation)

    assert evidence["checks"]["resource_limits_consistent"] is False


@pytest.mark.parametrize("provider", ["github", "llm"])
@pytest.mark.parametrize("field", ["rate_limit_responses", "transient_failures"])
def test_missing_provider_failure_exercise_is_failed_evidence(
    provider: str, field: str
) -> None:
    observation = valid_observation()
    item = observation["provider_profile"][provider]
    item["retry_successes"] -= item[field]
    item[field] = 0

    evidence = compile_valid(observation)

    assert evidence["checks"]["provider_failures_exercised"] is False


def test_inconsistent_provider_counts_are_rejected() -> None:
    observation = valid_observation()
    observation["provider_profile"]["github"]["retry_successes"] = 100

    with pytest.raises(ValueError, match="inconsistent"):
        compile_valid(observation)


def test_provider_p95_must_not_be_lower_than_p50() -> None:
    observation = valid_observation()
    observation["provider_profile"]["llm"]["latency_p95_seconds"] = 0.5

    with pytest.raises(ValueError, match="p95"):
        compile_valid(observation)


@pytest.mark.parametrize(
    "fault", ["worker_termination", "expired_lease", "network_interruption"]
)
def test_fault_job_loss_is_failed_evidence(fault: str) -> None:
    observation = valid_observation()
    observation["fault_injection"][fault]["lost_jobs"] = 1

    evidence = compile_valid(observation)

    assert evidence["checks"]["faults_recovered"] is False


def test_slow_fault_recovery_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["fault_injection"]["network_interruption"]["recovered_at"] = (
        "2025-09-02T03:33:00Z"
    )

    evidence = compile_valid(observation)

    assert evidence["checks"]["faults_recovered"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("completed_jobs", 179999),
        ("duplicate_completions", 1),
        ("lost_jobs", 1),
        ("exactly_once", False),
        ("queue_drained", False),
    ],
)
def test_completion_invariant_is_failed_evidence(field: str, value: int | bool) -> None:
    observation = valid_observation()
    observation["results"][field] = value

    evidence = compile_valid(observation)

    assert evidence["checks"]["exactly_once_and_drained"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_latency_p95_seconds", 61),
        ("completion_latency_p95_seconds", 121),
        ("start_slo_attainment_percent", 98),
        ("completion_slo_attainment_percent", 98),
    ],
)
def test_slo_breach_is_failed_evidence(field: str, value: int) -> None:
    observation = valid_observation()
    observation["results"][field] = value

    evidence = compile_valid(observation)

    assert evidence["checks"]["analysis_slo"] is False


@pytest.mark.parametrize(
    "field",
    ["worker_cpu_peak_percent", "worker_memory_peak_percent", "redis_memory_peak_percent"],
)
def test_resource_saturation_is_failed_evidence(field: str) -> None:
    observation = valid_observation()
    observation["resource_observation"][field] = 91

    evidence = compile_valid(observation)

    assert evidence["checks"]["resource_headroom"] is False


def test_postgres_peak_above_limit_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["resource_observation"]["postgres_total_peak_connections"] = 101

    evidence = compile_valid(observation)

    assert evidence["checks"]["resource_headroom"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recommended_rate_per_second", 41),
        ("headroom_percent", 19),
        ("reviewed", False),
    ],
)
def test_invalid_capacity_recommendation_is_failed_evidence(
    field: str, value: int | bool
) -> None:
    observation = valid_observation()
    observation["capacity_recommendation"][field] = value

    evidence = compile_valid(observation)

    assert evidence["checks"]["capacity_recommendation"] is False


def test_dirty_artifact_scan_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["artifacts"]["secret_scan_matches"] = 1

    evidence = compile_valid(observation)

    assert evidence["checks"]["artifact_secret_scan"] is False


def test_unknown_field_is_rejected_instead_of_leaking_secret() -> None:
    observation = valid_observation()
    observation["redis_password"] = "do-not-record"

    with pytest.raises(ValueError, match="unknown redis_password"):
        compile_valid(observation)


def test_resource_identifier_url_is_rejected() -> None:
    observation = valid_observation()
    observation["fault_injection"]["network_interruption"]["target"] = (
        "https://redis.internal"
    )

    with pytest.raises(ValueError, match="non-secret identifier"):
        compile_valid(observation)


def test_invalid_artifact_hash_is_rejected() -> None:
    observation = valid_observation()
    observation["artifacts"]["runner_sha256"] = "runner-output"

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        compile_valid(observation)


def test_fault_timeline_must_be_chronological() -> None:
    observation = valid_observation()
    observation["fault_injection"]["expired_lease"]["recovered_at"] = (
        "2025-09-02T02:59:00Z"
    )

    with pytest.raises(ValueError, match="chronological"):
        compile_valid(observation)


def test_fault_must_be_inside_soak_window() -> None:
    observation = valid_observation()
    observation["fault_injection"]["worker_termination"]["injected_at"] = (
        "2025-09-02T01:30:00Z"
    )

    with pytest.raises(ValueError, match="soak window"):
        compile_valid(observation)


def test_future_observation_is_rejected() -> None:
    with pytest.raises(ValueError, match="future"):
        compile_evidence(
            valid_observation(),
            "a" * 64,
            min_duration_seconds=3600,
            min_slo_attainment_percent=99,
            max_resource_utilization_percent=90,
            max_fault_recovery_seconds=120,
            checked_at=datetime(2025, 9, 1, tzinfo=UTC),
        )


def test_main_writes_failed_evidence_and_returns_one(tmp_path: Path) -> None:
    observation = valid_observation()
    observation["results"]["queue_drained"] = False
    input_path = tmp_path / "observation.json"
    output_path = tmp_path / "evidence.json"
    input_path.write_text(json.dumps(observation), encoding="utf-8")

    result = main(["--input", str(input_path), "--output", str(output_path)])

    assert result == 1
    assert json.loads(output_path.read_text(encoding="utf-8"))["passed"] is False


def test_main_refuses_to_replace_input(tmp_path: Path) -> None:
    input_path = tmp_path / "observation.json"
    input_path.write_text(json.dumps(valid_observation()), encoding="utf-8")

    with pytest.raises(SystemExit, match="must not replace"):
        main(["--input", str(input_path), "--output", str(input_path)])


def test_input_is_not_mutated() -> None:
    observation = valid_observation()
    original = copy.deepcopy(observation)

    compile_valid(observation)

    assert observation == original
