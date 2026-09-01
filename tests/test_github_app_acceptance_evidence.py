from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ops.acceptance.verify_github_app_evidence import (
    compile_evidence,
    load_observation,
    main,
)

EXAMPLE_PATH = Path("ops/acceptance/github-app-observation.example.json")
CHECKED_AT = datetime(2026, 9, 2, tzinfo=UTC)


def valid_observation() -> dict[str, Any]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def compile_valid(observation: dict[str, Any] | None = None) -> dict[str, Any]:
    return compile_evidence(
        observation or valid_observation(),
        "a" * 64,
        max_start_seconds=60,
        max_completion_seconds=120,
        checked_at=CHECKED_AT,
    )


def test_checked_in_example_passes_all_checks() -> None:
    observation, input_sha256 = load_observation(EXAMPLE_PATH)
    evidence = compile_evidence(
        observation,
        input_sha256,
        max_start_seconds=60,
        max_completion_seconds=120,
        checked_at=CHECKED_AT,
    )

    assert evidence["passed"] is True
    assert all(evidence["checks"].values())
    assert evidence["pr_run"]["start_seconds"] == 10
    assert evidence["pr_run"]["completion_seconds"] == 40
    assert evidence["branch_run"]["start_seconds"] == 14
    assert evidence["branch_run"]["completion_seconds"] == 52


def test_required_github_urls_and_run_ids_are_preserved() -> None:
    observation = valid_observation()
    evidence = compile_valid(observation)

    assert evidence["repository_url"] == observation["repository_url"]
    assert evidence["pr_run"]["run_id"] == observation["pr_run"]["run_id"]
    assert evidence["pr_run"]["comment_url"] == observation["pr_run"]["comment_url"]
    assert evidence["branch_run"]["check_url"] == observation["branch_run"]["check_url"]


@pytest.mark.parametrize(
    ("run_name", "timestamp", "check"),
    [
        ("pr_run", "2025-09-02T00:02:06Z", "pr_start_slo"),
        ("branch_run", "2025-09-02T00:04:07Z", "branch_start_slo"),
    ],
)
def test_slow_analysis_start_is_failed_evidence(
    run_name: str, timestamp: str, check: str
) -> None:
    observation = valid_observation()
    observation[run_name]["analysis_started_at"] = timestamp
    observation[run_name]["analysis_completed_at"] = timestamp
    observation[run_name]["published_at"] = timestamp

    evidence = compile_valid(observation)

    assert evidence["checks"][check] is False
    assert evidence["passed"] is False


def test_slow_analysis_completion_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["pr_run"]["analysis_completed_at"] = "2025-09-02T00:03:06Z"
    observation["pr_run"]["published_at"] = "2025-09-02T00:03:10Z"

    evidence = compile_valid(observation)

    assert evidence["checks"]["pr_completion_slo"] is False


def test_successful_workflow_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["pr_run"]["workflow_conclusion"] = "success"

    evidence = compile_valid(observation)

    assert evidence["checks"]["pr_workflow_failed"] is False


@pytest.mark.parametrize(
    "field", ["evidence_present", "related_files_present", "run_link_present"]
)
def test_missing_pr_content_is_failed_evidence(field: str) -> None:
    observation = valid_observation()
    observation["pr_run"][field] = False

    evidence = compile_valid(observation)

    assert evidence["checks"]["pr_content_complete"] is False


def test_duplicate_pr_comment_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["redelivery"]["pr_comment"]["count_after"] = 2

    evidence = compile_valid(observation)

    assert evidence["checks"]["pr_comment_idempotent"] is False


def test_replaced_branch_check_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["redelivery"]["branch_check"]["redelivery_url"] = (
        "https://github.com/example-org/pipelens-acceptance/runs/300000002"
    )

    evidence = compile_valid(observation)

    assert evidence["checks"]["branch_check_idempotent"] is False


@pytest.mark.parametrize(
    "field", ["published_matches", "persistence_matches", "provider_request_matches"]
)
def test_seeded_secret_match_is_failed_evidence(field: str) -> None:
    observation = valid_observation()
    observation["seeded_secret_scan"][field] = 1

    evidence = compile_valid(observation)

    assert evidence["checks"]["seeded_secret_absent"] is False


@pytest.mark.parametrize("field", ["llm_invocations", "commit_check_publications"])
def test_external_fork_side_effect_is_failed_evidence(field: str) -> None:
    observation = valid_observation()
    observation["external_fork"][field] = 1

    evidence = compile_valid(observation)

    assert evidence["checks"]["external_fork_isolated"] is False


def test_overprivileged_installation_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["permissions"]["contents"] = "write"

    evidence = compile_valid(observation)

    assert evidence["checks"]["least_privilege_permissions"] is False


def test_unknown_field_is_rejected_instead_of_leaking_secret() -> None:
    observation = valid_observation()
    observation["private_key"] = "do-not-record"

    with pytest.raises(ValueError, match="unknown private_key"):
        compile_valid(observation)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (
            ("repository_url",),
            "https://token@github.com/example-org/pipelens-acceptance",
            "credential-free",
        ),
        (
            ("pr_run", "run_url"),
            "https://github.com/example-org/pipelens-acceptance/actions/runs/100000001?token=x",
            "credential-free",
        ),
        (
            ("branch_run", "check_url"),
            "https://example.invalid/example-org/pipelens-acceptance/runs/300000001",
            "credential-free",
        ),
    ],
)
def test_unsafe_url_is_rejected(
    path: tuple[str, ...], value: str, message: str
) -> None:
    observation: Any = valid_observation()
    target = observation
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValueError, match=message):
        compile_valid(observation)


def test_url_from_another_repository_is_rejected() -> None:
    observation = valid_observation()
    observation["pr_run"]["comment_url"] = (
        "https://github.com/other-org/pipelens-acceptance/pull/42#issuecomment-200000001"
    )

    with pytest.raises(ValueError, match="repository_url"):
        compile_valid(observation)


def test_run_url_must_contain_declared_run_id() -> None:
    observation = valid_observation()
    observation["pr_run"]["run_id"] = 999

    with pytest.raises(ValueError, match="contain run_id"):
        compile_valid(observation)


def test_pr_comment_must_contain_declared_pr_number() -> None:
    observation = valid_observation()
    observation["pr_run"]["pull_request_number"] = 41

    with pytest.raises(ValueError, match="contain pull_request_number"):
        compile_valid(observation)


def test_invalid_seeded_secret_fingerprint_is_rejected() -> None:
    observation = valid_observation()
    observation["seeded_secret_scan"]["seeded_secret_sha256"] = "seeded-secret"

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        compile_valid(observation)


def test_run_timeline_must_be_chronological() -> None:
    observation = valid_observation()
    observation["pr_run"]["analysis_started_at"] = "2025-09-02T00:02:00Z"

    with pytest.raises(ValueError, match="chronological"):
        compile_valid(observation)


def test_run_timeline_must_be_inside_acceptance_window() -> None:
    observation = valid_observation()
    observation["started_at"] = "2025-09-02T00:02:00Z"

    with pytest.raises(ValueError, match="acceptance window"):
        compile_valid(observation)


def test_redelivery_must_follow_initial_publication() -> None:
    observation = valid_observation()
    observation["redelivery"]["pr_comment"]["redelivered_at"] = (
        "2025-09-02T00:01:40Z"
    )

    with pytest.raises(ValueError, match="follow initial publication"):
        compile_valid(observation)


def test_secret_scan_must_follow_all_exercises() -> None:
    observation = valid_observation()
    observation["seeded_secret_scan"]["checked_at"] = "2025-09-02T00:05:30Z"

    with pytest.raises(ValueError, match="follow all publication exercises"):
        compile_valid(observation)


def test_future_observation_is_rejected() -> None:
    with pytest.raises(ValueError, match="future"):
        compile_evidence(
            valid_observation(),
            "a" * 64,
            max_start_seconds=60,
            max_completion_seconds=120,
            checked_at=datetime(2025, 9, 1, tzinfo=UTC),
        )


def test_main_writes_failed_evidence_and_returns_one(tmp_path: Path) -> None:
    observation = valid_observation()
    observation["external_fork"]["llm_invocations"] = 1
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


def test_duplicate_run_ids_are_rejected() -> None:
    observation = valid_observation()
    observation["branch_run"]["run_id"] = observation["pr_run"]["run_id"]
    observation["branch_run"]["run_url"] = observation["pr_run"]["run_url"]

    with pytest.raises(ValueError, match="different run IDs"):
        compile_valid(observation)


def test_input_is_not_mutated() -> None:
    observation = valid_observation()
    original = copy.deepcopy(observation)

    compile_valid(observation)

    assert observation == original
