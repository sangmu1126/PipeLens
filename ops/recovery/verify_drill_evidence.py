"""Validate combined PostgreSQL, Grafana, cutover, and rollback drill evidence."""

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
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@#/-]{0,199}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
TOP_LEVEL_KEYS = {
    "schema_version",
    "drill_id",
    "source_revision",
    "environment",
    "started_at",
    "completed_at",
    "objectives_seconds",
    "postgres",
    "grafana",
    "cutover",
    "rollback",
    "artifacts",
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
    if not isinstance(value, str) or "://" in value or not SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a non-secret identifier of at most 200 characters")
    return value


def require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def positive_int(value: Any, label: str) -> int:
    result = non_negative_int(value, label)
    if result == 0:
        raise ValueError(f"{label} must be a positive integer")
    return result


def non_negative_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a non-negative finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be a non-negative finite number")
    return result


def positive_number(value: Any, label: str) -> float:
    result = non_negative_number(value, label)
    if result == 0:
        raise ValueError(f"{label} must be a positive finite number")
    return result


def sha256_value(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO 8601 timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO 8601 timestamp") from error
    if result.tzinfo is None:
        raise ValueError(f"{label} must include a UTC offset")
    return result.astimezone(UTC)


def ordered_timestamps(
    value: Mapping[str, Any], keys: Sequence[str], label: str
) -> dict[str, datetime]:
    result = {key: parse_timestamp(value[key], f"{label}.{key}") for key in keys}
    if any(left > right for left, right in pairwise(result.values())):
        raise ValueError(f"{label} timestamps must be chronological")
    return result


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


def parse_service(value: Any, label: str) -> dict[str, Any]:
    mapping = require_mapping(value, label)
    require_exact_keys(
        mapping,
        {
            "evidence_sha256",
            "backup_bytes",
            "representative_minimum_bytes",
            "backup_duration_seconds",
            "restore_duration_seconds",
            "recovery_seconds",
            "observed_rpo_seconds",
            "write_freeze_at",
            "backup_created_at",
            "restore_started_at",
            "validated_at",
            "integrity_checks_passed",
            "source_preserved",
        },
        label,
    )
    timeline = ordered_timestamps(
        mapping,
        ["write_freeze_at", "backup_created_at", "restore_started_at", "validated_at"],
        label,
    )
    return {
        "evidence_sha256": sha256_value(mapping["evidence_sha256"], f"{label}.evidence_sha256"),
        "backup_bytes": positive_int(mapping["backup_bytes"], f"{label}.backup_bytes"),
        "representative_minimum_bytes": positive_int(
            mapping["representative_minimum_bytes"], f"{label}.representative_minimum_bytes"
        ),
        "backup_duration_seconds": positive_number(
            mapping["backup_duration_seconds"], f"{label}.backup_duration_seconds"
        ),
        "restore_duration_seconds": positive_number(
            mapping["restore_duration_seconds"], f"{label}.restore_duration_seconds"
        ),
        "recovery_seconds": positive_number(
            mapping["recovery_seconds"], f"{label}.recovery_seconds"
        ),
        "observed_rpo_seconds": non_negative_number(
            mapping["observed_rpo_seconds"], f"{label}.observed_rpo_seconds"
        ),
        "timeline": {key: utc_timestamp(timestamp) for key, timestamp in timeline.items()},
        "integrity_checks_passed": require_bool(
            mapping["integrity_checks_passed"], f"{label}.integrity_checks_passed"
        ),
        "source_preserved": require_bool(
            mapping["source_preserved"], f"{label}.source_preserved"
        ),
    }


def compile_evidence(
    observation: Mapping[str, Any],
    input_sha256: str,
    *,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    require_exact_keys(observation, TOP_LEVEL_KEYS, "observation")
    if observation["schema_version"] != 1:
        raise ValueError("observation.schema_version must be 1")
    drill_id = safe_identifier(observation["drill_id"], "drill_id")
    source_revision = safe_identifier(observation["source_revision"], "source_revision")
    environment = safe_identifier(observation["environment"], "environment")
    started_at = parse_timestamp(observation["started_at"], "started_at")
    completed_at = parse_timestamp(observation["completed_at"], "completed_at")
    if completed_at <= started_at:
        raise ValueError("completed_at must follow started_at")

    objectives = require_mapping(observation["objectives_seconds"], "objectives_seconds")
    require_exact_keys(
        objectives, {"postgres_rto", "grafana_rto", "rpo", "rollback_rto"}, "objectives_seconds"
    )
    parsed_objectives = {
        key: positive_number(objectives[key], f"objectives_seconds.{key}")
        for key in ("postgres_rto", "grafana_rto", "rpo", "rollback_rto")
    }
    postgres = parse_service(observation["postgres"], "postgres")
    grafana = parse_service(observation["grafana"], "grafana")

    cutover = require_mapping(observation["cutover"], "cutover")
    require_exact_keys(
        cutover,
        {"approved_at", "started_at", "completed_at", "approved", "approver"},
        "cutover",
    )
    cutover_timeline = ordered_timestamps(
        cutover, ["approved_at", "started_at", "completed_at"], "cutover"
    )
    cutover_approved = require_bool(cutover["approved"], "cutover.approved")
    safe_identifier(cutover["approver"], "cutover.approver")

    rollback = require_mapping(observation["rollback"], "rollback")
    require_exact_keys(
        rollback,
        {
            "initiated_at",
            "completed_at",
            "used_preserved_postgres_source",
            "used_preserved_grafana_source",
            "postgres_integrity_verified",
            "grafana_content_verified",
            "grafana_access_policy_verified",
            "client_smoke_verified",
            "point_of_no_return_condition",
            "crossed_point_of_no_return",
            "reconciliation_plan_reviewed",
        },
        "rollback",
    )
    rollback_timeline = ordered_timestamps(
        rollback, ["initiated_at", "completed_at"], "rollback"
    )
    if rollback_timeline["initiated_at"] < cutover_timeline["completed_at"]:
        raise ValueError("rollback must follow completed cutover")
    rollback_duration = round(
        (rollback_timeline["completed_at"] - rollback_timeline["initiated_at"]).total_seconds(),
        3,
    )
    point_condition = safe_identifier(
        rollback["point_of_no_return_condition"], "rollback.point_of_no_return_condition"
    )
    rollback_flags = {
        key: require_bool(rollback[key], f"rollback.{key}")
        for key in (
            "used_preserved_postgres_source",
            "used_preserved_grafana_source",
            "postgres_integrity_verified",
            "grafana_content_verified",
            "grafana_access_policy_verified",
            "client_smoke_verified",
            "crossed_point_of_no_return",
            "reconciliation_plan_reviewed",
        )
    }

    artifacts = require_mapping(observation["artifacts"], "artifacts")
    require_exact_keys(
        artifacts,
        {"cutover_audit_sha256", "rollback_audit_sha256", "secret_scan_matches", "reviewed"},
        "artifacts",
    )
    parsed_artifacts = {
        "cutover_audit_sha256": sha256_value(
            artifacts["cutover_audit_sha256"], "artifacts.cutover_audit_sha256"
        ),
        "rollback_audit_sha256": sha256_value(
            artifacts["rollback_audit_sha256"], "artifacts.rollback_audit_sha256"
        ),
        "secret_scan_matches": non_negative_int(
            artifacts["secret_scan_matches"], "artifacts.secret_scan_matches"
        ),
        "reviewed": require_bool(artifacts["reviewed"], "artifacts.reviewed"),
    }

    service_times = [
        parse_timestamp(service["timeline"][key], f"{name}.{key}")
        for name, service in (("postgres", postgres), ("grafana", grafana))
        for key in ("write_freeze_at", "backup_created_at", "restore_started_at", "validated_at")
    ]
    all_times = [
        *service_times,
        *cutover_timeline.values(),
        *rollback_timeline.values(),
    ]
    if min(all_times) < started_at or max(all_times) > completed_at:
        raise ValueError("service, cutover, and rollback events must be within the drill window")
    now = (checked_at or datetime.now(UTC)).astimezone(UTC)
    if completed_at > now:
        raise ValueError("observation must not contain future events")

    def service_passed(service: Mapping[str, Any], rto: float) -> bool:
        return bool(
            service["backup_bytes"] >= service["representative_minimum_bytes"]
            and service["recovery_seconds"] <= rto
            and service["observed_rpo_seconds"] <= parsed_objectives["rpo"]
            and service["integrity_checks_passed"]
            and service["source_preserved"]
        )

    rollback_verified = all(
        rollback_flags[key]
        for key in (
            "used_preserved_postgres_source",
            "used_preserved_grafana_source",
            "postgres_integrity_verified",
            "grafana_content_verified",
            "grafana_access_policy_verified",
            "client_smoke_verified",
        )
    )
    checks = {
        "postgres_recovery": service_passed(postgres, parsed_objectives["postgres_rto"]),
        "grafana_recovery": service_passed(grafana, parsed_objectives["grafana_rto"]),
        "cutover_approved": cutover_approved,
        "rollback_verified": (
            rollback_verified and rollback_duration <= parsed_objectives["rollback_rto"]
        ),
        "point_of_no_return_controlled": (
            not rollback_flags["crossed_point_of_no_return"]
            or rollback_flags["reconciliation_plan_reviewed"]
        ),
        "artifacts_reviewed_and_clean": (
            parsed_artifacts["reviewed"] and parsed_artifacts["secret_scan_matches"] == 0
        ),
    }

    return {
        "schema_version": 1,
        "checked_at": utc_timestamp(now),
        "drill_id": drill_id,
        "source_revision": source_revision,
        "environment": environment,
        "drill_window": {
            "started_at": utc_timestamp(started_at),
            "completed_at": utc_timestamp(completed_at),
        },
        "objectives_seconds": parsed_objectives,
        "postgres": postgres,
        "grafana": grafana,
        "cutover": {
            "timeline": {
                key: utc_timestamp(timestamp) for key, timestamp in cutover_timeline.items()
            },
            "approved": cutover_approved,
            "approver_documented": True,
        },
        "rollback": {
            "timeline": {
                key: utc_timestamp(timestamp) for key, timestamp in rollback_timeline.items()
            },
            "duration_seconds": rollback_duration,
            "point_of_no_return_condition": point_condition,
            **rollback_flags,
        },
        "artifacts": parsed_artifacts,
        "checks": checks,
        "passed": all(checks.values()),
        "input_sha256": input_sha256,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("--output must not replace --input")
        observation, digest = load_observation(args.input)
        evidence = compile_evidence(observation, digest)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
