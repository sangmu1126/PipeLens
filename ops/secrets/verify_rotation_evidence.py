"""Validate a secret-manager and credential-rotation drill and emit redacted evidence."""

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
MANAGER_TYPES = {
    "aws-secrets-manager",
    "azure-key-vault",
    "gcp-secret-manager",
    "kubernetes-external-secrets",
    "other",
    "vault",
}
WORKLOADS = {"alertmanager", "api", "migration", "worker"}
REQUIRED_SECRETS = {
    "alertmanager_receiver",
    "database_url",
    "github_client_secret",
    "github_private_key",
    "redis_url",
    "session_secret",
    "token_encryption_fallback",
    "token_encryption_primary",
    "webhook_secret",
}
OPTIONAL_SECRETS = {"openai_api_key"}
EXTERNAL_CREDENTIALS = {
    "alertmanager_receiver",
    "database_url",
    "github_client_secret",
    "github_private_key",
    "openai_api_key",
    "redis_url",
    "webhook_secret",
}

TOP_LEVEL_KEYS = {
    "schema_version",
    "drill_id",
    "source_revision",
    "environment",
    "manager_type",
    "started_at",
    "completed_at",
    "inventory",
    "workload_identity",
    "fernet_rotation",
    "external_rotation",
    "unavailable_secret",
    "artifact_scans",
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


def require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def non_negative_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a non-negative finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a non-negative finite number")
    return number


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
    value: Mapping[str, Any], keys: Sequence[str], label: str
) -> dict[str, datetime]:
    parsed = {key: parse_timestamp(value[key], f"{label}.{key}") for key in keys}
    if any(left > right for left, right in pairwise(parsed.values())):
        raise ValueError(f"{label} timestamps must be chronological")
    return parsed


def utc_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def duration_seconds(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds(), 3)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


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


def parse_inventory(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("inventory must be a non-empty JSON array")
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed_names = REQUIRED_SECRETS | OPTIONAL_SECRETS
    expected = {
        "name",
        "workloads",
        "owner",
        "version",
        "created_at",
        "rotation_due_at",
        "injected_via_file",
        "read_only",
    }
    for index, item in enumerate(value):
        label = f"inventory[{index}]"
        mapping = require_mapping(item, label)
        require_exact_keys(mapping, expected, label)
        name = safe_identifier(mapping["name"], f"{label}.name")
        if name not in allowed_names:
            raise ValueError(f"{label}.name is not a supported credential")
        if name in seen:
            raise ValueError(f"inventory contains duplicate credential: {name}")
        seen.add(name)
        workloads = mapping["workloads"]
        if (
            not isinstance(workloads, list)
            or not workloads
            or not all(
                isinstance(workload, str) and workload in WORKLOADS
                for workload in workloads
            )
            or len(set(workloads)) != len(workloads)
        ):
            raise ValueError(f"{label}.workloads must contain unique supported workloads")
        owner = safe_identifier(mapping["owner"], f"{label}.owner")
        version = safe_identifier(mapping["version"], f"{label}.version")
        created_at = parse_timestamp(mapping["created_at"], f"{label}.created_at")
        rotation_due_at = parse_timestamp(
            mapping["rotation_due_at"], f"{label}.rotation_due_at"
        )
        if rotation_due_at <= created_at:
            raise ValueError(f"{label}.rotation_due_at must follow created_at")
        parsed.append(
            {
                "name": name,
                "workloads": sorted(workloads),
                "owner": owner,
                "version": version,
                "created_at": created_at,
                "rotation_due_at": rotation_due_at,
                "injected_via_file": require_bool(
                    mapping["injected_via_file"], f"{label}.injected_via_file"
                ),
                "read_only": require_bool(mapping["read_only"], f"{label}.read_only"),
            }
        )
    return parsed


def compile_evidence(
    observation: Mapping[str, Any],
    input_sha256: str,
    *,
    max_detection_seconds: float,
    max_recovery_seconds: float,
    max_unplanned_outage_seconds: float,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    require_exact_keys(observation, TOP_LEVEL_KEYS, "observation")
    if observation["schema_version"] != 1:
        raise ValueError("observation.schema_version must be 1")
    thresholds = (
        max_detection_seconds,
        max_recovery_seconds,
        max_unplanned_outage_seconds,
    )
    if any(not math.isfinite(value) or value < 0 for value in thresholds):
        raise ValueError("thresholds must be non-negative finite numbers")

    drill_id = safe_identifier(observation["drill_id"], "drill_id")
    source_revision = safe_identifier(observation["source_revision"], "source_revision")
    environment = safe_identifier(observation["environment"], "environment")
    manager_type = safe_identifier(observation["manager_type"], "manager_type")
    if manager_type not in MANAGER_TYPES:
        raise ValueError(f"manager_type must be one of {', '.join(sorted(MANAGER_TYPES))}")
    started_at = parse_timestamp(observation["started_at"], "started_at")
    completed_at = parse_timestamp(observation["completed_at"], "completed_at")
    if completed_at <= started_at:
        raise ValueError("completed_at must follow started_at")

    inventory = parse_inventory(observation["inventory"])
    inventory_by_name = {item["name"]: item for item in inventory}

    identity = require_mapping(observation["workload_identity"], "workload_identity")
    require_exact_keys(
        identity,
        {
            "identity",
            "authentication",
            "allowed_secret_count",
            "read_allowed",
            "list_allowed",
            "write_allowed",
            "delete_allowed",
            "long_lived_key_present",
            "policy_checked_at",
        },
        "workload_identity",
    )
    safe_identifier(identity["identity"], "workload_identity.identity")
    authentication = safe_identifier(
        identity["authentication"], "workload_identity.authentication"
    )
    allowed_secret_count = non_negative_int(
        identity["allowed_secret_count"], "workload_identity.allowed_secret_count"
    )
    policy_checked_at = parse_timestamp(
        identity["policy_checked_at"], "workload_identity.policy_checked_at"
    )
    identity_flags = {
        "read_allowed": require_bool(identity["read_allowed"], "workload_identity.read_allowed"),
        "list_allowed": require_bool(identity["list_allowed"], "workload_identity.list_allowed"),
        "write_allowed": require_bool(identity["write_allowed"], "workload_identity.write_allowed"),
        "delete_allowed": require_bool(
            identity["delete_allowed"], "workload_identity.delete_allowed"
        ),
        "long_lived_key_present": require_bool(
            identity["long_lived_key_present"], "workload_identity.long_lived_key_present"
        ),
    }

    fernet = require_mapping(observation["fernet_rotation"], "fernet_rotation")
    fernet_time_keys = (
        "new_version_created_at",
        "old_primary_new_fallback_deployed_at",
        "dual_read_verified_at",
        "new_primary_old_fallback_deployed_at",
        "lazy_rewrap_verified_at",
        "observation_window_ended_at",
        "old_fallback_removed_at",
        "post_removal_canary_at",
    )
    require_exact_keys(
        fernet,
        {
            "new_version",
            "old_version",
            *fernet_time_keys,
            "all_instances_updated",
            "old_deployments_terminated",
            "existing_session_verified",
        },
        "fernet_rotation",
    )
    new_fernet_version = safe_identifier(
        fernet["new_version"], "fernet_rotation.new_version"
    )
    old_fernet_version = safe_identifier(
        fernet["old_version"], "fernet_rotation.old_version"
    )
    if new_fernet_version == old_fernet_version:
        raise ValueError("Fernet new_version and old_version must differ")
    current_primary = inventory_by_name.get("token_encryption_primary")
    if current_primary is not None and new_fernet_version != current_primary["version"]:
        raise ValueError("Fernet new_version must match the primary inventory version")
    fernet_times = ordered_timestamps(fernet, fernet_time_keys, "fernet_rotation")
    fernet_flags = {
        "all_instances_updated": require_bool(
            fernet["all_instances_updated"], "fernet_rotation.all_instances_updated"
        ),
        "old_deployments_terminated": require_bool(
            fernet["old_deployments_terminated"],
            "fernet_rotation.old_deployments_terminated",
        ),
        "existing_session_verified": require_bool(
            fernet["existing_session_verified"],
            "fernet_rotation.existing_session_verified",
        ),
    }

    external = require_mapping(observation["external_rotation"], "external_rotation")
    external_time_keys = (
        "new_version_created_at",
        "new_version_deployed_at",
        "pre_revoke_canary_at",
        "old_version_revoked_at",
        "post_revoke_canary_at",
    )
    require_exact_keys(
        external,
        {
            "credential_name",
            "new_version",
            "old_version",
            *external_time_keys,
            "rollback_prepared",
            "unplanned_outage_seconds",
        },
        "external_rotation",
    )
    external_name = safe_identifier(
        external["credential_name"], "external_rotation.credential_name"
    )
    if external_name not in EXTERNAL_CREDENTIALS or external_name not in inventory_by_name:
        raise ValueError(
            "external_rotation.credential_name must reference an inventoried credential"
        )
    new_external_version = safe_identifier(
        external["new_version"], "external_rotation.new_version"
    )
    old_external_version = safe_identifier(
        external["old_version"], "external_rotation.old_version"
    )
    if new_external_version == old_external_version:
        raise ValueError("external credential new_version and old_version must differ")
    if new_external_version != inventory_by_name[external_name]["version"]:
        raise ValueError("external rotation new_version must match the inventory version")
    external_times = ordered_timestamps(external, external_time_keys, "external_rotation")
    rollback_prepared = require_bool(
        external["rollback_prepared"], "external_rotation.rollback_prepared"
    )
    unplanned_outage_seconds = non_negative_number(
        external["unplanned_outage_seconds"], "external_rotation.unplanned_outage_seconds"
    )

    unavailable = require_mapping(observation["unavailable_secret"], "unavailable_secret")
    unavailable_time_keys = (
        "unavailable_at",
        "detected_at",
        "incident_declared_at",
        "replacement_deployed_at",
        "recovered_at",
    )
    require_exact_keys(
        unavailable,
        {
            "credential_name",
            "incident_id",
            *unavailable_time_keys,
            "fail_closed",
            "secret_exposed",
        },
        "unavailable_secret",
    )
    unavailable_name = safe_identifier(
        unavailable["credential_name"], "unavailable_secret.credential_name"
    )
    if unavailable_name not in inventory_by_name:
        raise ValueError("unavailable_secret.credential_name must reference inventory")
    incident_id = safe_identifier(unavailable["incident_id"], "unavailable_secret.incident_id")
    unavailable_times = ordered_timestamps(
        unavailable, unavailable_time_keys, "unavailable_secret"
    )
    fail_closed = require_bool(unavailable["fail_closed"], "unavailable_secret.fail_closed")
    secret_exposed = require_bool(
        unavailable["secret_exposed"], "unavailable_secret.secret_exposed"
    )

    scans = require_mapping(observation["artifact_scans"], "artifact_scans")
    require_exact_keys(
        scans,
        {"repository_clean", "images_clean", "manifests_clean", "logs_clean", "checked_at"},
        "artifact_scans",
    )
    scans_checked_at = parse_timestamp(scans["checked_at"], "artifact_scans.checked_at")
    scan_flags = {
        key: require_bool(scans[key], f"artifact_scans.{key}")
        for key in ("repository_clean", "images_clean", "manifests_clean", "logs_clean")
    }

    event_times = [
        policy_checked_at,
        *fernet_times.values(),
        *external_times.values(),
        *unavailable_times.values(),
        scans_checked_at,
    ]
    if any(value < started_at or value > completed_at for value in event_times):
        raise ValueError("all drill event timestamps must fall between started_at and completed_at")
    if any(item["created_at"] > completed_at for item in inventory):
        raise ValueError("inventory created_at cannot follow completed_at")
    checked = (checked_at or datetime.now(UTC)).astimezone(UTC)
    if completed_at > checked:
        raise ValueError("drill timestamps cannot be in the future")

    detection_seconds = duration_seconds(
        unavailable_times["unavailable_at"], unavailable_times["detected_at"]
    )
    recovery_seconds = duration_seconds(
        unavailable_times["unavailable_at"], unavailable_times["recovered_at"]
    )
    inventory_names = set(inventory_by_name)
    checks = {
        "inventory_complete": inventory_names >= REQUIRED_SECRETS,
        "rotation_deadlines_current": all(
            item["rotation_due_at"] > completed_at for item in inventory
        ),
        "file_injection": all(item["injected_via_file"] for item in inventory),
        "read_only_mounts": all(item["read_only"] for item in inventory),
        "least_privilege_identity": (
            authentication == "workload_identity"
            and allowed_secret_count == len(inventory)
            and identity_flags["read_allowed"]
            and not identity_flags["list_allowed"]
            and not identity_flags["write_allowed"]
            and not identity_flags["delete_allowed"]
            and not identity_flags["long_lived_key_present"]
        ),
        "fernet_rolling_rotation": all(fernet_flags.values()),
        "external_credential_rotation": (
            rollback_prepared and unplanned_outage_seconds <= max_unplanned_outage_seconds
        ),
        "unavailable_secret_response": (
            fail_closed
            and not secret_exposed
            and detection_seconds <= max_detection_seconds
            and recovery_seconds <= max_recovery_seconds
        ),
        "artifact_scans_clean": all(scan_flags.values()),
    }
    return {
        "schema_version": 1,
        "checked_at": utc_timestamp(checked),
        "drill_id": drill_id,
        "source_revision": source_revision,
        "environment": environment,
        "manager_type": manager_type,
        "input_sha256": input_sha256,
        "inventory": [
            {
                "name": item["name"],
                "workloads": item["workloads"],
                "owner_documented": True,
                "version_fingerprint": fingerprint(item["version"]),
                "created_at": utc_timestamp(item["created_at"]),
                "rotation_due_at": utc_timestamp(item["rotation_due_at"]),
                "injected_via_file": item["injected_via_file"],
                "read_only": item["read_only"],
            }
            for item in sorted(inventory, key=lambda current: current["name"])
        ],
        "workload_identity": {
            "authentication": authentication,
            "identity_documented": True,
            "allowed_secret_count": allowed_secret_count,
            **identity_flags,
            "policy_checked_at": utc_timestamp(policy_checked_at),
        },
        "rotations": {
            "fernet": {
                "new_version_fingerprint": fingerprint(new_fernet_version),
                "old_version_fingerprint": fingerprint(old_fernet_version),
                "timeline": {
                    key: utc_timestamp(value) for key, value in fernet_times.items()
                },
                **fernet_flags,
            },
            "external": {
                "credential_name": external_name,
                "new_version_fingerprint": fingerprint(new_external_version),
                "old_version_fingerprint": fingerprint(old_external_version),
                "timeline": {
                    key: utc_timestamp(value) for key, value in external_times.items()
                },
                "rollback_prepared": rollback_prepared,
                "unplanned_outage_seconds": unplanned_outage_seconds,
            },
        },
        "unavailable_secret": {
            "credential_name": unavailable_name,
            "incident_id": incident_id,
            "timeline": {
                key: utc_timestamp(value) for key, value in unavailable_times.items()
            },
            "detection_seconds": detection_seconds,
            "recovery_seconds": recovery_seconds,
            "fail_closed": fail_closed,
            "secret_exposed": secret_exposed,
        },
        "artifact_scans": {**scan_flags, "checked_at": utc_timestamp(scans_checked_at)},
        "threshold_seconds": {
            "detection": max_detection_seconds,
            "recovery": max_recovery_seconds,
            "unplanned_outage": max_unplanned_outage_seconds,
        },
        "timeline": {
            "started_at": utc_timestamp(started_at),
            "completed_at": utc_timestamp(completed_at),
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-detection-seconds", type=float, default=60)
    parser.add_argument("--max-recovery-seconds", type=float, default=300)
    parser.add_argument("--max-unplanned-outage-seconds", type=float, default=0)
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
            max_detection_seconds=args.max_detection_seconds,
            max_recovery_seconds=args.max_recovery_seconds,
            max_unplanned_outage_seconds=args.max_unplanned_outage_seconds,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
