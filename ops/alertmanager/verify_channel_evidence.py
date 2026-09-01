"""Validate a production-channel exercise timeline and emit redacted evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 1024 * 1024
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@#-]{0,199}$")
RECEIVER_TYPES = {"incidentio", "pagerduty", "slack", "webhook", "other"}

TOP_LEVEL_KEYS = {
    "schema_version",
    "source_revision",
    "environment",
    "receiver_type",
    "owner",
    "escalation_policy_ref",
    "alertmanager_group",
    "external_incident_id",
    "probe",
    "grouping",
    "deduplication",
    "inhibition",
    "silence",
    "credential_rotation",
    "receiver_failure",
}


def require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a JSON object")
    return value


def require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    missing = expected - value.keys()
    unknown = value.keys() - expected
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown {', '.join(sorted(unknown))}")
        raise ValueError(f"{label} has invalid fields: {'; '.join(details)}")


def safe_identifier(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or "://" in value
        or not SAFE_IDENTIFIER.fullmatch(value)
    ):
        raise ValueError(f"{label} must be a non-secret identifier of at most 200 characters")
    return value


def non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed.astimezone(UTC)


def ordered_timestamps(
    value: Any,
    keys: Sequence[str],
    label: str,
) -> dict[str, datetime]:
    mapping = require_mapping(value, label)
    require_exact_keys(mapping, set(keys), label)
    parsed = {key: parse_timestamp(mapping[key], f"{label}.{key}") for key in keys}
    if any(left > right for left, right in pairwise(parsed.values())):
        raise ValueError(f"{label} timestamps must be chronological")
    return parsed


def duration_seconds(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds(), 3)


def utc_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def load_observation(path: Path) -> tuple[Mapping[str, Any], str]:
    if not path.is_file():
        raise ValueError("--input must be an existing regular file")
    size = path.stat().st_size
    if not 0 < size <= MAX_INPUT_BYTES:
        raise ValueError("--input must contain between 1 byte and 1 MiB")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("--input must contain UTF-8 JSON") from error
    return require_mapping(payload, "observation"), hashlib.sha256(raw).hexdigest()


def count_check(value: Any, label: str, first: str, second: str) -> tuple[int, int]:
    mapping = require_mapping(value, label)
    require_exact_keys(mapping, {first, second}, label)
    return (
        non_negative_int(mapping[first], f"{label}.{first}"),
        non_negative_int(mapping[second], f"{label}.{second}"),
    )


def compile_evidence(
    observation: Mapping[str, Any],
    input_sha256: str,
    *,
    max_delivery_seconds: float,
    max_acknowledgement_seconds: float,
    max_resolve_delivery_seconds: float,
    max_retry_seconds: float,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    require_exact_keys(observation, TOP_LEVEL_KEYS, "observation")
    if observation["schema_version"] != 1:
        raise ValueError("observation.schema_version must be 1")
    if any(
        not math.isfinite(threshold) or threshold <= 0
        for threshold in (
            max_delivery_seconds,
            max_acknowledgement_seconds,
            max_resolve_delivery_seconds,
            max_retry_seconds,
        )
    ):
        raise ValueError("latency thresholds must be positive")

    source_revision = safe_identifier(observation["source_revision"], "source_revision")
    environment = safe_identifier(observation["environment"], "environment")
    receiver_type = safe_identifier(observation["receiver_type"], "receiver_type")
    if receiver_type not in RECEIVER_TYPES:
        raise ValueError(f"receiver_type must be one of {', '.join(sorted(RECEIVER_TYPES))}")
    safe_identifier(observation["owner"], "owner")
    safe_identifier(observation["escalation_policy_ref"], "escalation_policy_ref")
    alertmanager_group = safe_identifier(observation["alertmanager_group"], "alertmanager_group")
    external_incident_id = safe_identifier(
        observation["external_incident_id"], "external_incident_id"
    )

    probe = ordered_timestamps(
        observation["probe"],
        (
            "firing_sent_at",
            "firing_delivered_at",
            "acknowledged_at",
            "resolved_sent_at",
            "resolved_delivered_at",
        ),
        "probe",
    )
    source_alerts, grouped_notifications = count_check(
        observation["grouping"], "grouping", "source_alerts", "notifications"
    )
    repeated_firings, new_incidents = count_check(
        observation["deduplication"],
        "deduplication",
        "repeated_firings",
        "new_external_incidents",
    )
    inhibited_candidates, inhibited_deliveries = count_check(
        observation["inhibition"], "inhibition", "candidates", "deliveries"
    )
    silenced_candidates, silenced_deliveries = count_check(
        observation["silence"], "silence", "candidates", "deliveries"
    )

    rotation_mapping = require_mapping(observation["credential_rotation"], "credential_rotation")
    require_exact_keys(
        rotation_mapping,
        {
            "before_sent_at",
            "before_delivered_at",
            "rotated_at",
            "after_sent_at",
            "after_delivered_at",
            "old_credential_revoked",
        },
        "credential_rotation",
    )
    rotation = ordered_timestamps(
        {key: rotation_mapping[key] for key in rotation_mapping if key != "old_credential_revoked"},
        (
            "before_sent_at",
            "before_delivered_at",
            "rotated_at",
            "after_sent_at",
            "after_delivered_at",
        ),
        "credential_rotation",
    )
    old_credential_revoked = rotation_mapping["old_credential_revoked"]
    if not isinstance(old_credential_revoked, bool):
        raise ValueError("credential_rotation.old_credential_revoked must be a boolean")

    failure_mapping = require_mapping(observation["receiver_failure"], "receiver_failure")
    require_exact_keys(
        failure_mapping,
        {"failure_started_at", "alert_sent_at", "recovered_at", "delivered_at", "attempts"},
        "receiver_failure",
    )
    failure = ordered_timestamps(
        {key: failure_mapping[key] for key in failure_mapping if key != "attempts"},
        ("failure_started_at", "alert_sent_at", "recovered_at", "delivered_at"),
        "receiver_failure",
    )
    retry_attempts = non_negative_int(failure_mapping["attempts"], "receiver_failure.attempts")

    checked = (checked_at or datetime.now(UTC)).astimezone(UTC)
    latest_observed = max(
        [*probe.values(), *rotation.values(), *failure.values()]
    )
    if latest_observed > checked:
        raise ValueError("observation timestamps cannot be in the future")

    delivery_latency = duration_seconds(probe["firing_sent_at"], probe["firing_delivered_at"])
    acknowledgement_latency = duration_seconds(
        probe["firing_delivered_at"], probe["acknowledged_at"]
    )
    resolve_delivery_latency = duration_seconds(
        probe["resolved_sent_at"], probe["resolved_delivered_at"]
    )
    rotation_before_latency = duration_seconds(
        rotation["before_sent_at"], rotation["before_delivered_at"]
    )
    rotation_after_latency = duration_seconds(
        rotation["after_sent_at"], rotation["after_delivered_at"]
    )
    retry_latency = duration_seconds(failure["alert_sent_at"], failure["delivered_at"])

    checks = {
        "firing_delivery": delivery_latency <= max_delivery_seconds,
        "resolved_delivery": resolve_delivery_latency <= max_resolve_delivery_seconds,
        "acknowledgement": acknowledgement_latency <= max_acknowledgement_seconds,
        "grouping": source_alerts >= 2 and grouped_notifications == 1,
        "deduplication": repeated_firings >= 1 and new_incidents == 0,
        "inhibition": inhibited_candidates >= 1 and inhibited_deliveries == 0,
        "silence": silenced_candidates >= 1 and silenced_deliveries == 0,
        "credential_rotation": (
            old_credential_revoked
            and rotation_before_latency <= max_delivery_seconds
            and rotation_after_latency <= max_delivery_seconds
        ),
        "receiver_retry": retry_attempts >= 2 and retry_latency <= max_retry_seconds,
    }
    return {
        "schema_version": 1,
        "checked_at": utc_timestamp(checked),
        "source_revision": source_revision,
        "environment": environment,
        "receiver_type": receiver_type,
        "ownership": {
            "owner_documented": True,
            "escalation_policy_documented": True,
        },
        "incident": {
            "alertmanager_group": alertmanager_group,
            "external_incident_id": external_incident_id,
        },
        "timeline": {
            "probe": {key: utc_timestamp(value) for key, value in probe.items()},
            "credential_rotation": {
                key: utc_timestamp(value) for key, value in rotation.items()
            },
            "receiver_failure": {
                key: utc_timestamp(value) for key, value in failure.items()
            },
        },
        "latency_seconds": {
            "firing_delivery": delivery_latency,
            "acknowledgement": acknowledgement_latency,
            "resolved_delivery": resolve_delivery_latency,
            "rotation_before_delivery": rotation_before_latency,
            "rotation_after_delivery": rotation_after_latency,
            "receiver_retry": retry_latency,
        },
        "threshold_seconds": {
            "delivery": max_delivery_seconds,
            "acknowledgement": max_acknowledgement_seconds,
            "resolved_delivery": max_resolve_delivery_seconds,
            "receiver_retry": max_retry_seconds,
        },
        "exercise_counts": {
            "grouping_source_alerts": source_alerts,
            "grouping_notifications": grouped_notifications,
            "deduplication_repeated_firings": repeated_firings,
            "deduplication_new_external_incidents": new_incidents,
            "inhibition_candidates": inhibited_candidates,
            "inhibition_deliveries": inhibited_deliveries,
            "silence_candidates": silenced_candidates,
            "silence_deliveries": silenced_deliveries,
            "receiver_retry_attempts": retry_attempts,
        },
        "checks": checks,
        "passed": all(checks.values()),
        "input_sha256": input_sha256,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-delivery-seconds", type=float, default=120)
    parser.add_argument("--max-acknowledgement-seconds", type=float, default=300)
    parser.add_argument("--max-resolve-delivery-seconds", type=float, default=120)
    parser.add_argument("--max-retry-seconds", type=float, default=300)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("--output must not replace --input")
        observation, input_sha256 = load_observation(args.input)
        evidence = compile_evidence(
            observation,
            input_sha256,
            max_delivery_seconds=args.max_delivery_seconds,
            max_acknowledgement_seconds=args.max_acknowledgement_seconds,
            max_resolve_delivery_seconds=args.max_resolve_delivery_seconds,
            max_retry_seconds=args.max_retry_seconds,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
