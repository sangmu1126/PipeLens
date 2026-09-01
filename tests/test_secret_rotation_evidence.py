from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ops.secrets.verify_rotation_evidence import compile_evidence, load_observation, main

EXAMPLE_PATH = Path("ops/secrets/rotation-observation.example.json")
CHECKED_AT = datetime(2026, 9, 2, tzinfo=UTC)


def valid_observation() -> dict[str, Any]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def compile_valid(observation: dict[str, Any] | None = None) -> dict[str, Any]:
    return compile_evidence(
        observation or valid_observation(),
        "a" * 64,
        max_detection_seconds=60,
        max_recovery_seconds=300,
        max_unplanned_outage_seconds=0,
        checked_at=CHECKED_AT,
    )


def inventory_item(observation: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in observation["inventory"] if item["name"] == name)


def test_checked_in_example_passes_all_checks() -> None:
    observation, input_sha256 = load_observation(EXAMPLE_PATH)
    evidence = compile_evidence(
        observation,
        input_sha256,
        max_detection_seconds=60,
        max_recovery_seconds=300,
        max_unplanned_outage_seconds=0,
        checked_at=CHECKED_AT,
    )

    assert evidence["passed"] is True
    assert all(evidence["checks"].values())
    assert len(evidence["inventory"]) == 9
    assert evidence["unavailable_secret"]["detection_seconds"] == 10.0
    assert evidence["unavailable_secret"]["recovery_seconds"] == 120.0


def test_evidence_redacts_identity_owner_and_version_values() -> None:
    observation = valid_observation()
    evidence = compile_valid(observation)
    serialized = json.dumps(evidence)

    assert observation["workload_identity"]["identity"] not in serialized
    for item in observation["inventory"]:
        assert item["owner"] not in serialized
        assert item["version"] not in serialized
    assert evidence["inventory"][0]["owner_documented"] is True
    assert len(evidence["inventory"][0]["version_fingerprint"]) == 16


def test_missing_required_inventory_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["inventory"] = [
        item for item in observation["inventory"] if item["name"] != "webhook_secret"
    ]
    observation["workload_identity"]["allowed_secret_count"] = 8

    evidence = compile_valid(observation)

    assert evidence["passed"] is False
    assert evidence["checks"]["inventory_complete"] is False


@pytest.mark.parametrize("field", ["injected_via_file", "read_only"])
def test_insecure_injection_is_failed_evidence(field: str) -> None:
    observation = valid_observation()
    inventory_item(observation, "session_secret")[field] = False

    evidence = compile_valid(observation)

    assert evidence["passed"] is False


def test_overprivileged_identity_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["workload_identity"]["list_allowed"] = True

    evidence = compile_valid(observation)

    assert evidence["checks"]["least_privilege_identity"] is False


def test_fernet_timeline_must_be_chronological() -> None:
    observation = valid_observation()
    observation["fernet_rotation"]["lazy_rewrap_verified_at"] = "2025-09-02T00:19:00Z"

    with pytest.raises(ValueError, match="chronological"):
        compile_valid(observation)


def test_external_version_must_match_inventory() -> None:
    observation = valid_observation()
    observation["external_rotation"]["new_version"] = "not-in-inventory"

    with pytest.raises(ValueError, match="match the inventory"):
        compile_valid(observation)


def test_fernet_version_must_match_primary_inventory() -> None:
    observation = valid_observation()
    observation["fernet_rotation"]["new_version"] = "not-in-inventory"

    with pytest.raises(ValueError, match="primary inventory"):
        compile_valid(observation)


def test_external_outage_above_threshold_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["external_rotation"]["unplanned_outage_seconds"] = 1

    evidence = compile_valid(observation)

    assert evidence["checks"]["external_credential_rotation"] is False


def test_slow_unavailable_secret_response_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["unavailable_secret"]["detected_at"] = "2025-09-02T01:21:10Z"
    observation["unavailable_secret"]["incident_declared_at"] = "2025-09-02T01:21:20Z"

    evidence = compile_valid(observation)

    assert evidence["checks"]["unavailable_secret_response"] is False


def test_dirty_artifact_scan_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["artifact_scans"]["logs_clean"] = False

    evidence = compile_valid(observation)

    assert evidence["checks"]["artifact_scans_clean"] is False


def test_unknown_field_is_rejected_instead_of_leaking_secret() -> None:
    observation = valid_observation()
    observation["secret_value"] = "do-not-record"

    with pytest.raises(ValueError, match="unknown secret_value"):
        compile_valid(observation)


def test_duplicate_inventory_is_rejected() -> None:
    observation = valid_observation()
    observation["inventory"].append(copy.deepcopy(observation["inventory"][0]))

    with pytest.raises(ValueError, match="duplicate credential"):
        compile_valid(observation)


def test_resource_urls_are_rejected() -> None:
    observation = valid_observation()
    observation["workload_identity"]["identity"] = "https://manager.invalid/identity"

    with pytest.raises(ValueError, match="non-secret identifier"):
        compile_valid(observation)


def test_future_drill_is_rejected() -> None:
    with pytest.raises(ValueError, match="future"):
        compile_evidence(
            valid_observation(),
            "a" * 64,
            max_detection_seconds=60,
            max_recovery_seconds=300,
            max_unplanned_outage_seconds=0,
            checked_at=datetime(2025, 9, 1, tzinfo=UTC),
        )


def test_main_writes_failed_evidence_and_returns_one(tmp_path: Path) -> None:
    observation = valid_observation()
    observation["artifact_scans"]["images_clean"] = False
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
