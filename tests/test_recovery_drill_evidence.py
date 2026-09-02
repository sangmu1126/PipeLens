from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ops.recovery.verify_drill_evidence import compile_evidence, load_observation, main

EXAMPLE_PATH = Path("ops/recovery/drill-observation.example.json")
CHECKED_AT = datetime(2026, 9, 2, tzinfo=UTC)


def valid_observation() -> dict[str, Any]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def compile_valid(observation: dict[str, Any] | None = None) -> dict[str, Any]:
    return compile_evidence(observation or valid_observation(), "a" * 64, checked_at=CHECKED_AT)


def test_checked_in_example_passes_all_checks() -> None:
    observation, digest = load_observation(EXAMPLE_PATH)
    evidence = compile_evidence(observation, digest, checked_at=CHECKED_AT)

    assert evidence["passed"] is True
    assert all(evidence["checks"].values())
    assert evidence["rollback"]["duration_seconds"] == 480
    assert evidence["postgres"]["backup_bytes"] == 5_368_709_120


def test_approver_is_redacted() -> None:
    observation = valid_observation()
    approver = observation["cutover"]["approver"]

    evidence = compile_valid(observation)

    assert approver not in json.dumps(evidence)
    assert evidence["cutover"]["approver_documented"] is True


@pytest.mark.parametrize("service", ["postgres", "grafana"])
def test_non_representative_backup_is_failed_evidence(service: str) -> None:
    observation = valid_observation()
    observation[service]["backup_bytes"] = observation[service]["representative_minimum_bytes"] - 1

    evidence = compile_valid(observation)

    assert evidence["checks"][f"{service}_recovery"] is False


@pytest.mark.parametrize("service", ["postgres", "grafana"])
def test_rto_breach_is_failed_evidence(service: str) -> None:
    observation = valid_observation()
    objective = f"{service}_rto"
    observation[service]["recovery_seconds"] = observation["objectives_seconds"][objective] + 1

    evidence = compile_valid(observation)

    assert evidence["checks"][f"{service}_recovery"] is False


@pytest.mark.parametrize("service", ["postgres", "grafana"])
def test_rpo_breach_is_failed_evidence(service: str) -> None:
    observation = valid_observation()
    observation[service]["observed_rpo_seconds"] = 301

    evidence = compile_valid(observation)

    assert evidence["checks"][f"{service}_recovery"] is False


@pytest.mark.parametrize("service", ["postgres", "grafana"])
@pytest.mark.parametrize("field", ["integrity_checks_passed", "source_preserved"])
def test_incomplete_restore_is_failed_evidence(service: str, field: str) -> None:
    observation = valid_observation()
    observation[service][field] = False

    evidence = compile_valid(observation)

    assert evidence["checks"][f"{service}_recovery"] is False


def test_unapproved_cutover_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["cutover"]["approved"] = False

    evidence = compile_valid(observation)

    assert evidence["checks"]["cutover_approved"] is False


@pytest.mark.parametrize(
    "field",
    [
        "used_preserved_postgres_source",
        "used_preserved_grafana_source",
        "postgres_integrity_verified",
        "grafana_content_verified",
        "grafana_access_policy_verified",
        "client_smoke_verified",
    ],
)
def test_incomplete_rollback_is_failed_evidence(field: str) -> None:
    observation = valid_observation()
    observation["rollback"][field] = False

    evidence = compile_valid(observation)

    assert evidence["checks"]["rollback_verified"] is False


def test_slow_rollback_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["rollback"]["completed_at"] = "2025-09-02T05:56:00Z"

    evidence = compile_valid(observation)

    assert evidence["checks"]["rollback_verified"] is False


def test_crossed_point_of_no_return_requires_reconciliation_review() -> None:
    observation = valid_observation()
    observation["rollback"]["crossed_point_of_no_return"] = True

    evidence = compile_valid(observation)

    assert evidence["checks"]["point_of_no_return_controlled"] is False


def test_reviewed_reconciliation_allows_crossed_point_of_no_return() -> None:
    observation = valid_observation()
    observation["rollback"]["crossed_point_of_no_return"] = True
    observation["rollback"]["reconciliation_plan_reviewed"] = True

    evidence = compile_valid(observation)

    assert evidence["checks"]["point_of_no_return_controlled"] is True


@pytest.mark.parametrize(("field", "value"), [("reviewed", False), ("secret_scan_matches", 1)])
def test_unreviewed_or_dirty_artifacts_are_failed_evidence(
    field: str, value: bool | int
) -> None:
    observation = valid_observation()
    observation["artifacts"][field] = value

    evidence = compile_valid(observation)

    assert evidence["checks"]["artifacts_reviewed_and_clean"] is False


def test_unknown_field_is_rejected_instead_of_leaking_secret() -> None:
    observation = valid_observation()
    observation["database_url"] = "do-not-record"

    with pytest.raises(ValueError, match="unknown database_url"):
        compile_valid(observation)


def test_resource_url_is_rejected() -> None:
    observation = valid_observation()
    observation["rollback"]["point_of_no_return_condition"] = "https://internal/runbook"

    with pytest.raises(ValueError, match="non-secret identifier"):
        compile_valid(observation)


def test_invalid_evidence_hash_is_rejected() -> None:
    observation = valid_observation()
    observation["postgres"]["evidence_sha256"] = "postgres-evidence"

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        compile_valid(observation)


def test_service_timeline_must_be_chronological() -> None:
    observation = valid_observation()
    observation["grafana"]["restore_started_at"] = "2025-09-02T05:04:00Z"

    with pytest.raises(ValueError, match="chronological"):
        compile_valid(observation)


def test_rollback_must_follow_cutover() -> None:
    observation = valid_observation()
    observation["rollback"]["initiated_at"] = "2025-09-02T05:34:00Z"

    with pytest.raises(ValueError, match="follow completed cutover"):
        compile_valid(observation)


def test_events_must_be_inside_drill_window() -> None:
    observation = valid_observation()
    observation["started_at"] = "2025-09-02T05:06:00Z"

    with pytest.raises(ValueError, match="drill window"):
        compile_valid(observation)


def test_future_observation_is_rejected() -> None:
    with pytest.raises(ValueError, match="future"):
        compile_evidence(
            valid_observation(), "a" * 64, checked_at=datetime(2025, 9, 1, tzinfo=UTC)
        )


def test_main_writes_failed_evidence_and_returns_one(tmp_path: Path) -> None:
    observation = valid_observation()
    observation["rollback"]["client_smoke_verified"] = False
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
