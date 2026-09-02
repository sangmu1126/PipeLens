from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ops.acceptance.verify_https_e2e_evidence import (
    compile_evidence,
    load_observation,
    main,
    public_https_origin,
)

EXAMPLE_PATH = Path("ops/acceptance/https-e2e-observation.example.json")
CHECKED_AT = datetime(2026, 9, 2, tzinfo=UTC)


def valid_observation() -> dict[str, Any]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def compile_valid(observation: dict[str, Any] | None = None) -> dict[str, Any]:
    return compile_evidence(
        observation or valid_observation(),
        "a" * 64,
        max_webhook_response_seconds=10,
        checked_at=CHECKED_AT,
    )


def test_checked_in_example_passes_all_checks() -> None:
    observation, input_sha256 = load_observation(EXAMPLE_PATH)
    evidence = compile_evidence(
        observation,
        input_sha256,
        max_webhook_response_seconds=10,
        checked_at=CHECKED_AT,
    )

    assert evidence["passed"] is True
    assert all(evidence["checks"].values())
    assert evidence["webhook"]["response_seconds"] == 0.5
    assert evidence["configured_urls"]["webhook"].endswith("/webhooks/github")


def test_output_preserves_only_redacted_artifact_identifiers() -> None:
    evidence = compile_valid()
    serialized = json.dumps(evidence)

    assert "evidence_sha256" in serialized
    assert "delivery_id_sha256" in serialized
    assert "cookie_value" not in serialized
    assert "signature_value" not in serialized
    assert "oauth_code" not in serialized


@pytest.mark.parametrize(
    "origin",
    [
        "http://pipelens.example.com",
        "https://user:password@pipelens.example.com",
        "https://pipelens.example.com/app",
        "https://pipelens.example.com?debug=true",
        "https://localhost",
        "https://127.0.0.1",
        "https://internal",
        "https://bad_label.example.com",
    ],
)
def test_non_public_or_unsafe_origin_is_rejected(origin: str) -> None:
    with pytest.raises(ValueError):
        public_https_origin(origin)


def test_origin_with_explicit_port_is_normalized() -> None:
    assert public_https_origin("https://PipeLens.Example.com:8443/") == (
        "https://pipelens.example.com:8443"
    )


def test_failed_preflight_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["preflight"]["passed"] = False

    evidence = compile_valid(observation)

    assert evidence["checks"]["preflight_passed"] is False


def test_preflight_from_another_origin_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["preflight"]["origin"] = "https://other.example.com"

    evidence = compile_valid(observation)

    assert evidence["checks"]["preflight_passed"] is False


@pytest.mark.parametrize(
    ("field", "path"),
    [
        ("oauth_callback", "/wrong/callback"),
        ("setup", "/wrong/setup"),
        ("webhook", "/wrong/webhook"),
    ],
)
def test_wrong_configured_url_is_failed_evidence(field: str, path: str) -> None:
    observation = valid_observation()
    observation["configured_urls"][field] = f"https://pipelens.example.com{path}"

    evidence = compile_valid(observation)

    assert evidence["checks"]["configured_urls_exact"] is False


def test_configured_url_from_another_origin_is_rejected() -> None:
    observation = valid_observation()
    observation["configured_urls"]["webhook"] = (
        "https://other.example.com/webhooks/github"
    )

    with pytest.raises(ValueError, match="on origin"):
        compile_valid(observation)


@pytest.mark.parametrize(
    ("cookie_name", "field", "value"),
    [
        ("oauth_state_cookie", "secure", False),
        ("oauth_state_cookie", "httponly", False),
        ("oauth_state_cookie", "samesite", "none"),
        ("session_cookie", "secure", False),
        ("session_cookie", "httponly", False),
        ("session_cookie", "samesite", "strict"),
    ],
)
def test_insecure_cookie_is_failed_evidence(
    cookie_name: str, field: str, value: bool | str
) -> None:
    observation = valid_observation()
    observation["browser_flow"][cookie_name][field] = value

    evidence = compile_valid(observation)

    assert evidence["checks"]["cookie_security"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [("installation_count", 0), ("session_invalid_after_logout", False)],
)
def test_incomplete_browser_flow_is_failed_evidence(field: str, value: int | bool) -> None:
    observation = valid_observation()
    observation["browser_flow"][field] = value

    evidence = compile_valid(observation)

    assert evidence["checks"]["browser_flow_complete"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_scheme", "http"),
        ("observed_host", "internal.example.com"),
        ("application_origin", "https://internal.example.com"),
        ("oauth_redirect_uri", "https://pipelens.example.com/wrong/callback"),
    ],
)
def test_wrong_forwarding_observation_is_failed_evidence(field: str, value: str) -> None:
    observation = valid_observation()
    observation["forwarding"][field] = value

    evidence = compile_valid(observation)

    assert evidence["checks"]["forwarding_exact"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event", "push"),
        ("action", "requested"),
        ("signature_valid", False),
        ("response_status_code", 401),
    ],
)
def test_invalid_webhook_is_failed_evidence(field: str, value: str | bool | int) -> None:
    observation = valid_observation()
    observation["webhook"][field] = value

    evidence = compile_valid(observation)

    assert evidence["checks"]["signed_workflow_webhook"] is False


def test_slow_webhook_response_is_failed_evidence() -> None:
    observation = valid_observation()
    observation["webhook"]["responded_at"] = "2025-09-02T01:04:11Z"

    evidence = compile_valid(observation)

    assert evidence["checks"]["webhook_response_slo"] is False


def test_unknown_field_is_rejected_instead_of_leaking_secret() -> None:
    observation = valid_observation()
    observation["oauth_client_secret"] = "do-not-record"

    with pytest.raises(ValueError, match="unknown oauth_client_secret"):
        compile_valid(observation)


def test_invalid_artifact_hash_is_rejected() -> None:
    observation = valid_observation()
    observation["webhook"]["request_evidence_sha256"] = "request-capture"

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        compile_valid(observation)


def test_browser_timeline_must_be_chronological() -> None:
    observation = valid_observation()
    observation["browser_flow"]["oauth_authorized_at"] = "2025-09-02T01:03:00Z"

    with pytest.raises(ValueError, match="chronological"):
        compile_valid(observation)


def test_webhook_timeline_must_be_chronological() -> None:
    observation = valid_observation()
    observation["webhook"]["signature_verified_at"] = "2025-09-02T01:05:00Z"

    with pytest.raises(ValueError, match="chronological"):
        compile_valid(observation)


def test_events_must_be_inside_acceptance_window() -> None:
    observation = valid_observation()
    observation["started_at"] = "2025-09-02T01:01:30Z"

    with pytest.raises(ValueError, match="acceptance window"):
        compile_valid(observation)


def test_preflight_must_precede_browser_flow() -> None:
    observation = valid_observation()
    observation["preflight"]["checked_at"] = "2025-09-02T01:01:10Z"

    with pytest.raises(ValueError, match="acceptance window"):
        compile_valid(observation)


def test_forwarding_must_be_observed_during_browser_navigation() -> None:
    observation = valid_observation()
    observation["forwarding"]["checked_at"] = "2025-09-02T01:03:00Z"

    with pytest.raises(ValueError, match="acceptance window"):
        compile_valid(observation)


def test_future_observation_is_rejected() -> None:
    with pytest.raises(ValueError, match="future"):
        compile_evidence(
            valid_observation(),
            "a" * 64,
            max_webhook_response_seconds=10,
            checked_at=datetime(2025, 9, 1, tzinfo=UTC),
        )


def test_negative_threshold_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative finite"):
        compile_evidence(
            valid_observation(),
            "a" * 64,
            max_webhook_response_seconds=-1,
            checked_at=CHECKED_AT,
        )


def test_main_writes_failed_evidence_and_returns_one(tmp_path: Path) -> None:
    observation = valid_observation()
    observation["browser_flow"]["session_invalid_after_logout"] = False
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
