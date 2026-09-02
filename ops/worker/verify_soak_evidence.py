"""Validate production-representative worker soak observations and capacity evidence."""

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
    "soak_id",
    "source_revision",
    "environment",
    "started_at",
    "completed_at",
    "load_profile",
    "resource_limits",
    "provider_profile",
    "fault_injection",
    "results",
    "resource_observation",
    "capacity_recommendation",
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


def percentage(value: Any, label: str) -> float:
    result = non_negative_number(value, label)
    if result > 100:
        raise ValueError(f"{label} must be between 0 and 100")
    return result


def sha256_value(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")
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


def parse_provider(value: Any, label: str) -> dict[str, Any]:
    mapping = require_mapping(value, label)
    require_exact_keys(
        mapping,
        {
            "requests",
            "latency_p50_seconds",
            "latency_p95_seconds",
            "rate_limit_responses",
            "transient_failures",
            "retry_successes",
        },
        label,
    )
    requests = positive_int(mapping["requests"], f"{label}.requests")
    p50 = positive_number(mapping["latency_p50_seconds"], f"{label}.latency_p50_seconds")
    p95 = positive_number(mapping["latency_p95_seconds"], f"{label}.latency_p95_seconds")
    if p95 < p50:
        raise ValueError(f"{label} p95 latency must not be lower than p50")
    rate_limits = non_negative_int(mapping["rate_limit_responses"], f"{label}.rate_limit_responses")
    transient = non_negative_int(mapping["transient_failures"], f"{label}.transient_failures")
    retry_successes = non_negative_int(mapping["retry_successes"], f"{label}.retry_successes")
    if rate_limits + transient > requests or retry_successes > rate_limits + transient:
        raise ValueError(f"{label} failure and retry counts are inconsistent")
    return {
        "requests": requests,
        "latency_p50_seconds": p50,
        "latency_p95_seconds": p95,
        "rate_limit_responses": rate_limits,
        "transient_failures": transient,
        "retry_successes": retry_successes,
    }


def parse_fault(
    value: Any, label: str, *, count_key: str, extra_keys: set[str] | None = None
) -> dict[str, Any]:
    mapping = require_mapping(value, label)
    expected = {"injected_at", "recovered_at", count_key, "lost_jobs"} | (extra_keys or set())
    require_exact_keys(mapping, expected, label)
    timeline = ordered_timestamps(mapping, ["injected_at", "recovered_at"], label)
    result: dict[str, Any] = {
        "timeline": {key: utc_timestamp(timestamp) for key, timestamp in timeline.items()},
        count_key: positive_int(mapping[count_key], f"{label}.{count_key}"),
        "lost_jobs": non_negative_int(mapping["lost_jobs"], f"{label}.lost_jobs"),
        "recovery_seconds": round(
            (timeline["recovered_at"] - timeline["injected_at"]).total_seconds(), 3
        ),
    }
    for key in extra_keys or set():
        result[key] = safe_identifier(mapping[key], f"{label}.{key}")
    return result


def compile_evidence(
    observation: Mapping[str, Any],
    input_sha256: str,
    *,
    min_duration_seconds: float,
    min_slo_attainment_percent: float,
    max_resource_utilization_percent: float,
    max_fault_recovery_seconds: float,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    require_exact_keys(observation, TOP_LEVEL_KEYS, "observation")
    if observation["schema_version"] != 1:
        raise ValueError("observation.schema_version must be 1")
    thresholds = (
        min_duration_seconds,
        min_slo_attainment_percent,
        max_resource_utilization_percent,
        max_fault_recovery_seconds,
    )
    if any(not math.isfinite(value) or value < 0 for value in thresholds):
        raise ValueError("thresholds must be non-negative finite numbers")
    if min_slo_attainment_percent > 100 or max_resource_utilization_percent > 100:
        raise ValueError("percentage thresholds must not exceed 100")

    soak_id = safe_identifier(observation["soak_id"], "soak_id")
    source_revision = safe_identifier(observation["source_revision"], "source_revision")
    environment = safe_identifier(observation["environment"], "environment")
    started_at = parse_timestamp(observation["started_at"], "started_at")
    completed_at = parse_timestamp(observation["completed_at"], "completed_at")
    if completed_at <= started_at:
        raise ValueError("completed_at must follow started_at")
    observed_duration = round((completed_at - started_at).total_seconds(), 3)

    load = require_mapping(observation["load_profile"], "load_profile")
    require_exact_keys(
        load,
        {
            "jobs",
            "arrival_rate_per_second",
            "burst_size",
            "concurrency",
            "planned_duration_seconds",
        },
        "load_profile",
    )
    load_profile = {
        "jobs": positive_int(load["jobs"], "load_profile.jobs"),
        "arrival_rate_per_second": positive_number(
            load["arrival_rate_per_second"], "load_profile.arrival_rate_per_second"
        ),
        "burst_size": positive_int(load["burst_size"], "load_profile.burst_size"),
        "concurrency": positive_int(load["concurrency"], "load_profile.concurrency"),
        "planned_duration_seconds": positive_number(
            load["planned_duration_seconds"], "load_profile.planned_duration_seconds"
        ),
    }
    if load_profile["burst_size"] > load_profile["jobs"]:
        raise ValueError("load_profile.burst_size must not exceed jobs")

    limits = require_mapping(observation["resource_limits"], "resource_limits")
    require_exact_keys(
        limits,
        {
            "worker_replicas",
            "worker_cpu_cores_each",
            "worker_memory_mib_each",
            "postgres_pool_size_each",
            "postgres_max_connections",
            "redis_maxmemory_mib",
        },
        "resource_limits",
    )
    resource_limits = {
        "worker_replicas": positive_int(
            limits["worker_replicas"], "resource_limits.worker_replicas"
        ),
        "worker_cpu_cores_each": positive_number(
            limits["worker_cpu_cores_each"], "resource_limits.worker_cpu_cores_each"
        ),
        "worker_memory_mib_each": positive_number(
            limits["worker_memory_mib_each"], "resource_limits.worker_memory_mib_each"
        ),
        "postgres_pool_size_each": positive_int(
            limits["postgres_pool_size_each"], "resource_limits.postgres_pool_size_each"
        ),
        "postgres_max_connections": positive_int(
            limits["postgres_max_connections"], "resource_limits.postgres_max_connections"
        ),
        "redis_maxmemory_mib": positive_number(
            limits["redis_maxmemory_mib"], "resource_limits.redis_maxmemory_mib"
        ),
    }

    providers = require_mapping(observation["provider_profile"], "provider_profile")
    require_exact_keys(providers, {"github", "llm"}, "provider_profile")
    provider_profile = {
        name: parse_provider(providers[name], f"provider_profile.{name}")
        for name in ("github", "llm")
    }

    faults = require_mapping(observation["fault_injection"], "fault_injection")
    require_exact_keys(
        faults, {"worker_termination", "expired_lease", "network_interruption"}, "fault_injection"
    )
    parsed_faults = {
        "worker_termination": parse_fault(
            faults["worker_termination"], "fault_injection.worker_termination", count_key="workers"
        ),
        "expired_lease": parse_fault(
            faults["expired_lease"], "fault_injection.expired_lease", count_key="recovered_jobs"
        ),
        "network_interruption": parse_fault(
            faults["network_interruption"],
            "fault_injection.network_interruption",
            count_key="interruptions",
            extra_keys={"target"},
        ),
    }

    results = require_mapping(observation["results"], "results")
    require_exact_keys(
        results,
        {
            "completed_jobs",
            "throughput_jobs_per_second",
            "start_latency_p95_seconds",
            "completion_latency_p95_seconds",
            "start_slo_attainment_percent",
            "completion_slo_attainment_percent",
            "duplicate_completions",
            "lost_jobs",
            "exactly_once",
            "queue_drained",
        },
        "results",
    )
    parsed_results = {
        "completed_jobs": non_negative_int(results["completed_jobs"], "results.completed_jobs"),
        "throughput_jobs_per_second": positive_number(
            results["throughput_jobs_per_second"], "results.throughput_jobs_per_second"
        ),
        "start_latency_p95_seconds": non_negative_number(
            results["start_latency_p95_seconds"], "results.start_latency_p95_seconds"
        ),
        "completion_latency_p95_seconds": non_negative_number(
            results["completion_latency_p95_seconds"], "results.completion_latency_p95_seconds"
        ),
        "start_slo_attainment_percent": percentage(
            results["start_slo_attainment_percent"], "results.start_slo_attainment_percent"
        ),
        "completion_slo_attainment_percent": percentage(
            results["completion_slo_attainment_percent"],
            "results.completion_slo_attainment_percent",
        ),
        "duplicate_completions": non_negative_int(
            results["duplicate_completions"], "results.duplicate_completions"
        ),
        "lost_jobs": non_negative_int(results["lost_jobs"], "results.lost_jobs"),
        "exactly_once": require_bool(results["exactly_once"], "results.exactly_once"),
        "queue_drained": require_bool(results["queue_drained"], "results.queue_drained"),
    }

    resources = require_mapping(observation["resource_observation"], "resource_observation")
    require_exact_keys(
        resources,
        {
            "captured_at",
            "worker_cpu_peak_percent",
            "worker_memory_peak_percent",
            "postgres_pool_peak_connections",
            "postgres_total_peak_connections",
            "redis_memory_peak_percent",
        },
        "resource_observation",
    )
    resource_observation = {
        "captured_at": utc_timestamp(
            parse_timestamp(resources["captured_at"], "resource_observation.captured_at")
        ),
        "worker_cpu_peak_percent": percentage(
            resources["worker_cpu_peak_percent"], "resource_observation.worker_cpu_peak_percent"
        ),
        "worker_memory_peak_percent": percentage(
            resources["worker_memory_peak_percent"],
            "resource_observation.worker_memory_peak_percent",
        ),
        "postgres_pool_peak_connections": positive_int(
            resources["postgres_pool_peak_connections"],
            "resource_observation.postgres_pool_peak_connections",
        ),
        "postgres_total_peak_connections": positive_int(
            resources["postgres_total_peak_connections"],
            "resource_observation.postgres_total_peak_connections",
        ),
        "redis_memory_peak_percent": percentage(
            resources["redis_memory_peak_percent"],
            "resource_observation.redis_memory_peak_percent",
        ),
    }

    capacity = require_mapping(observation["capacity_recommendation"], "capacity_recommendation")
    require_exact_keys(
        capacity,
        {
            "max_sustained_rate_per_second",
            "recommended_rate_per_second",
            "recommended_worker_replicas",
            "headroom_percent",
            "limiting_resource",
            "owner",
            "reviewed",
        },
        "capacity_recommendation",
    )
    capacity_recommendation = {
        "max_sustained_rate_per_second": positive_number(
            capacity["max_sustained_rate_per_second"],
            "capacity_recommendation.max_sustained_rate_per_second",
        ),
        "recommended_rate_per_second": positive_number(
            capacity["recommended_rate_per_second"],
            "capacity_recommendation.recommended_rate_per_second",
        ),
        "recommended_worker_replicas": positive_int(
            capacity["recommended_worker_replicas"],
            "capacity_recommendation.recommended_worker_replicas",
        ),
        "headroom_percent": percentage(
            capacity["headroom_percent"], "capacity_recommendation.headroom_percent"
        ),
        "limiting_resource": safe_identifier(
            capacity["limiting_resource"], "capacity_recommendation.limiting_resource"
        ),
        "owner_documented": bool(
            safe_identifier(capacity["owner"], "capacity_recommendation.owner")
        ),
        "reviewed": require_bool(capacity["reviewed"], "capacity_recommendation.reviewed"),
    }

    artifacts = require_mapping(observation["artifacts"], "artifacts")
    require_exact_keys(
        artifacts,
        {"runner_sha256", "telemetry_sha256", "provider_audit_sha256", "secret_scan_matches"},
        "artifacts",
    )
    parsed_artifacts = {
        "runner_sha256": sha256_value(artifacts["runner_sha256"], "artifacts.runner_sha256"),
        "telemetry_sha256": sha256_value(
            artifacts["telemetry_sha256"], "artifacts.telemetry_sha256"
        ),
        "provider_audit_sha256": sha256_value(
            artifacts["provider_audit_sha256"], "artifacts.provider_audit_sha256"
        ),
        "secret_scan_matches": non_negative_int(
            artifacts["secret_scan_matches"], "artifacts.secret_scan_matches"
        ),
    }

    all_fault_times = [
        parse_timestamp(item["timeline"][key], f"fault_injection.{name}.{key}")
        for name, item in parsed_faults.items()
        for key in ("injected_at", "recovered_at")
    ]
    resource_captured_at = parse_timestamp(
        resource_observation["captured_at"], "resource_observation.captured_at"
    )
    if min([resource_captured_at, *all_fault_times]) < started_at or max(
        [resource_captured_at, *all_fault_times]
    ) > completed_at:
        raise ValueError("resource and fault events must be within the soak window")
    now = (checked_at or datetime.now(UTC)).astimezone(UTC)
    if completed_at > now:
        raise ValueError("observation must not contain future events")

    pool_budget = (
        resource_limits["worker_replicas"] * resource_limits["postgres_pool_size_each"]
    )
    provider_exercises = all(
        item["rate_limit_responses"] >= 1
        and item["transient_failures"] >= 1
        and item["retry_successes"] == item["rate_limit_responses"] + item["transient_failures"]
        for item in provider_profile.values()
    )
    faults_recovered = all(
        item["lost_jobs"] == 0 and item["recovery_seconds"] <= max_fault_recovery_seconds
        for item in parsed_faults.values()
    )
    resource_safe = (
        resource_observation["worker_cpu_peak_percent"] <= max_resource_utilization_percent
        and resource_observation["worker_memory_peak_percent"] <= max_resource_utilization_percent
        and resource_observation["redis_memory_peak_percent"] <= max_resource_utilization_percent
        and resource_observation["postgres_pool_peak_connections"] <= pool_budget
        and resource_observation["postgres_total_peak_connections"]
        <= resource_limits["postgres_max_connections"]
    )
    capacity_consistent = (
        capacity_recommendation["recommended_rate_per_second"]
        <= capacity_recommendation["max_sustained_rate_per_second"]
        and capacity_recommendation["recommended_rate_per_second"]
        >= load_profile["arrival_rate_per_second"]
        and capacity_recommendation["headroom_percent"] >= 20
        and capacity_recommendation["reviewed"]
    )
    checks = {
        "production_duration": (
            observed_duration >= min_duration_seconds
            and load_profile["planned_duration_seconds"] >= min_duration_seconds
        ),
        "resource_limits_consistent": pool_budget <= resource_limits["postgres_max_connections"],
        "provider_failures_exercised": provider_exercises,
        "faults_recovered": faults_recovered,
        "exactly_once_and_drained": (
            parsed_results["completed_jobs"] == load_profile["jobs"]
            and parsed_results["duplicate_completions"] == 0
            and parsed_results["lost_jobs"] == 0
            and parsed_results["exactly_once"]
            and parsed_results["queue_drained"]
        ),
        "analysis_slo": (
            parsed_results["start_latency_p95_seconds"] <= 60
            and parsed_results["completion_latency_p95_seconds"] <= 120
            and parsed_results["start_slo_attainment_percent"] >= min_slo_attainment_percent
            and parsed_results["completion_slo_attainment_percent"] >= min_slo_attainment_percent
        ),
        "resource_headroom": resource_safe,
        "capacity_recommendation": capacity_consistent,
        "artifact_secret_scan": parsed_artifacts["secret_scan_matches"] == 0,
    }

    return {
        "schema_version": 1,
        "checked_at": utc_timestamp(now),
        "soak_id": soak_id,
        "source_revision": source_revision,
        "environment": environment,
        "soak_window": {
            "started_at": utc_timestamp(started_at),
            "completed_at": utc_timestamp(completed_at),
            "observed_duration_seconds": observed_duration,
        },
        "load_profile": load_profile,
        "resource_limits": resource_limits,
        "provider_profile": provider_profile,
        "fault_injection": parsed_faults,
        "results": parsed_results,
        "resource_observation": resource_observation,
        "capacity_recommendation": capacity_recommendation,
        "artifacts": parsed_artifacts,
        "thresholds": {
            "minimum_duration_seconds": min_duration_seconds,
            "minimum_slo_attainment_percent": min_slo_attainment_percent,
            "maximum_resource_utilization_percent": max_resource_utilization_percent,
            "maximum_fault_recovery_seconds": max_fault_recovery_seconds,
        },
        "checks": checks,
        "passed": all(checks.values()),
        "input_sha256": input_sha256,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-duration-seconds", type=float, default=3600)
    parser.add_argument("--min-slo-attainment-percent", type=float, default=99)
    parser.add_argument("--max-resource-utilization-percent", type=float, default=90)
    parser.add_argument("--max-fault-recovery-seconds", type=float, default=120)
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
            min_duration_seconds=args.min_duration_seconds,
            min_slo_attainment_percent=args.min_slo_attainment_percent,
            max_resource_utilization_percent=args.max_resource_utilization_percent,
            max_fault_recovery_seconds=args.max_fault_recovery_seconds,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
