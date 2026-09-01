from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ops.alertmanager.verify_channel_evidence import (
    compile_evidence,
    load_observation,
    main,
)

CHECKED_AT = datetime(2026, 9, 2, 1, 0, tzinfo=UTC)


def valid_observation() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_revision": "release-2026-09-02",
        "environment": "staging",
        "receiver_type": "pagerduty",
        "owner": "platform-oncall",
        "escalation_policy_ref": "policy/oncall-primary",
        "alertmanager_group": "pipelens-critical-staging",
        "external_incident_id": "INC-2026-0042",
        "probe": {
            "firing_sent_at": "2025-09-02T00:00:00Z",
            "firing_delivered_at": "2025-09-02T00:00:12Z",
            "acknowledged_at": "2025-09-02T00:00:42Z",
            "resolved_sent_at": "2025-09-02T00:05:00Z",
            "resolved_delivered_at": "2025-09-02T00:05:14Z",
        },
        "grouping": {"source_alerts": 2, "notifications": 1},
        "deduplication": {"repeated_firings": 2, "new_external_incidents": 0},
        "inhibition": {"candidates": 1, "deliveries": 0},
        "silence": {"candidates": 1, "deliveries": 0},
        "credential_rotation": {
            "before_sent_at": "2025-09-02T00:10:00Z",
            "before_delivered_at": "2025-09-02T00:10:10Z",
            "rotated_at": "2025-09-02T00:11:00Z",
            "after_sent_at": "2025-09-02T00:12:00Z",
            "after_delivered_at": "2025-09-02T00:12:11Z",
            "old_credential_revoked": True,
        },
        "receiver_failure": {
            "failure_started_at": "2025-09-02T00:20:00Z",
            "alert_sent_at": "2025-09-02T00:20:05Z",
            "recovered_at": "2025-09-02T00:21:00Z",
            "delivered_at": "2025-09-02T00:21:08Z",
            "attempts": 3,
        },
    }


def compile_valid(observation: dict[str, object] | None = None) -> dict[str, object]:
    return compile_evidence(
        observation or valid_observation(),
        "a" * 64,
        max_delivery_seconds=60,
        max_acknowledgement_seconds=120,
        max_resolve_delivery_seconds=60,
        max_retry_seconds=120,
        checked_at=CHECKED_AT,
    )


def test_compile_evidence_passes_all_channel_exercises() -> None:
    evidence = compile_valid()

    assert evidence["passed"] is True
    assert all(evidence["checks"].values())  # type: ignore[union-attr]
    assert evidence["latency_seconds"] == {
        "firing_delivery": 12.0,
        "acknowledgement": 30.0,
        "resolved_delivery": 14.0,
        "rotation_before_delivery": 10.0,
        "rotation_after_delivery": 11.0,
        "receiver_retry": 63.0,
    }
    assert evidence["incident"] == {
        "alertmanager_group": "pipelens-critical-staging",
        "external_incident_id": "INC-2026-0042",
    }
    assert evidence["timeline"]["probe"]["firing_sent_at"] == "2025-09-02T00:00:00Z"  # type: ignore[index]


def test_evidence_excludes_owner_and_policy_details() -> None:
    observation = valid_observation()
    evidence = compile_valid(observation)
    serialized = json.dumps(evidence)

    assert observation["owner"] not in serialized
    assert observation["escalation_policy_ref"] not in serialized
    assert evidence["ownership"] == {
        "owner_documented": True,
        "escalation_policy_documented": True,
    }


def test_unknown_fields_are_rejected_instead_of_leaking_secrets() -> None:
    observation = valid_observation()
    observation["routing_key"] = "super-secret"

    with pytest.raises(ValueError, match="unknown routing_key"):
        compile_valid(observation)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("receiver_type", "email"),
        ("external_incident_id", "https://incident.invalid/incident-42"),
        ("owner", "platform oncall"),
    ],
)
def test_unsafe_operational_identifiers_are_rejected(field: str, value: str) -> None:
    observation = valid_observation()
    observation[field] = value

    with pytest.raises(ValueError):
        compile_valid(observation)


def test_non_chronological_probe_is_rejected() -> None:
    observation = valid_observation()
    probe = observation["probe"]
    assert isinstance(probe, dict)
    probe["acknowledged_at"] = "2025-09-01T23:59:59Z"

    with pytest.raises(ValueError, match="chronological"):
        compile_valid(observation)


def test_future_observation_is_rejected() -> None:
    observation = valid_observation()

    with pytest.raises(ValueError, match="future"):
        compile_evidence(
            observation,
            "a" * 64,
            max_delivery_seconds=60,
            max_acknowledgement_seconds=120,
            max_resolve_delivery_seconds=60,
            max_retry_seconds=120,
            checked_at=datetime(2025, 9, 1, tzinfo=UTC),
        )


def test_failed_acceptance_checks_are_emitted_without_schema_failure() -> None:
    observation = valid_observation()
    observation["grouping"] = {"source_alerts": 2, "notifications": 2}
    observation["silence"] = {"candidates": 1, "deliveries": 1}
    evidence = compile_valid(observation)

    assert evidence["passed"] is False
    assert evidence["checks"]["grouping"] is False  # type: ignore[index]
    assert evidence["checks"]["silence"] is False  # type: ignore[index]


@pytest.mark.parametrize("threshold", [0, -1, float("nan"), float("inf")])
def test_invalid_latency_threshold_is_rejected(threshold: float) -> None:
    with pytest.raises(ValueError, match="thresholds"):
        compile_evidence(
            valid_observation(),
            "a" * 64,
            max_delivery_seconds=threshold,
            max_acknowledgement_seconds=120,
            max_resolve_delivery_seconds=60,
            max_retry_seconds=120,
            checked_at=CHECKED_AT,
        )


def test_main_writes_failed_evidence_and_returns_one(tmp_path: Path) -> None:
    observation = valid_observation()
    observation["receiver_failure"] = {
        "failure_started_at": "2026-09-01T00:20:00Z",
        "alert_sent_at": "2026-09-01T00:20:05Z",
        "recovered_at": "2026-09-01T00:21:00Z",
        "delivered_at": "2026-09-01T00:21:08Z",
        "attempts": 1,
    }
    input_path = tmp_path / "observation.json"
    output_path = tmp_path / "evidence.json"
    input_path.write_text(json.dumps(observation), encoding="utf-8")

    result = main(["--input", str(input_path), "--output", str(output_path)])

    assert result == 1
    assert json.loads(output_path.read_text(encoding="utf-8"))["passed"] is False


def test_load_observation_rejects_oversized_input(tmp_path: Path) -> None:
    input_path = tmp_path / "large.json"
    input_path.write_bytes(b"x" * (1024 * 1024 + 1))

    with pytest.raises(ValueError, match="1 MiB"):
        load_observation(input_path)


def test_main_refuses_to_replace_input(tmp_path: Path) -> None:
    input_path = tmp_path / "observation.json"
    input_path.write_text(json.dumps(valid_observation()), encoding="utf-8")

    with pytest.raises(SystemExit, match="must not replace"):
        main(["--input", str(input_path), "--output", str(input_path)])


def test_checked_in_example_is_valid() -> None:
    path = Path("ops/alertmanager/fixtures/channel-observation.example.json")
    observation, input_sha256 = load_observation(path)

    evidence = compile_evidence(
        observation,
        input_sha256,
        max_delivery_seconds=120,
        max_acknowledgement_seconds=300,
        max_resolve_delivery_seconds=120,
        max_retry_seconds=300,
        checked_at=CHECKED_AT,
    )

    assert evidence["passed"] is True
    assert evidence["environment"] == "staging-example"
