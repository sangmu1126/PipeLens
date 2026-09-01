"""Validate redacted evidence from a real GitHub App acceptance run."""

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
from urllib.parse import urlsplit

MAX_INPUT_BYTES = 1024 * 1024
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@#/-]{0,199}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
REPOSITORY_PATH = re.compile(r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")
RUN_PATH = re.compile(r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/actions/runs/([1-9][0-9]*)$")
COMMENT_PATH = re.compile(
    r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)"
    r"#issuecomment-([1-9][0-9]*)$"
)
CHECK_PATH = re.compile(
    r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/(?:runs|checks)/([1-9][0-9]*)$"
)
EXPECTED_PERMISSIONS = {
    "actions": "read",
    "checks": "write",
    "contents": "read",
    "metadata": "read",
    "pull_requests": "write",
}
TOP_LEVEL_KEYS = {
    "schema_version",
    "acceptance_id",
    "source_revision",
    "environment",
    "repository_url",
    "installation_id",
    "permissions",
    "started_at",
    "completed_at",
    "pr_run",
    "branch_run",
    "redelivery",
    "seeded_secret_scan",
    "external_fork",
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


def positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
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
    parsed = {key: parse_timestamp(value[key], f"{label}.{key}") for key in keys}
    if any(left > right for left, right in pairwise(parsed.values())):
        raise ValueError(f"{label} timestamps must be chronological")
    return parsed


def utc_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def duration_seconds(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds(), 3)


def github_url(value: Any, label: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a GitHub HTTPS URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
    ):
        raise ValueError(f"{label} must be a credential-free github.com HTTPS URL")
    target = parsed.path + (f"#{parsed.fragment}" if parsed.fragment else "")
    match = pattern.fullmatch(target)
    if match is None:
        raise ValueError(f"{label} has an unsupported GitHub URL shape")
    return match.groups()


def same_repository(parts: Sequence[str], repository: tuple[str, str], label: str) -> None:
    if tuple(parts[:2]) != repository:
        raise ValueError(f"{label} must belong to repository_url")


def parse_run(
    value: Any,
    label: str,
    repository: tuple[str, str],
    *,
    publication_key: str,
    publication_pattern: re.Pattern[str],
) -> dict[str, Any]:
    mapping = require_mapping(value, label)
    expected = {
        "run_id",
        "run_url",
        "workflow_conclusion",
        "workflow_failed_at",
        "webhook_recorded_at",
        "analysis_started_at",
        "analysis_completed_at",
        "published_at",
        publication_key,
    }
    if publication_key == "comment_url":
        expected |= {
            "pull_request_number",
            "evidence_present",
            "related_files_present",
            "run_link_present",
        }
    require_exact_keys(mapping, expected, label)
    run_id = positive_int(mapping["run_id"], f"{label}.run_id")
    run_parts = github_url(mapping["run_url"], f"{label}.run_url", RUN_PATH)
    same_repository(run_parts, repository, f"{label}.run_url")
    if int(run_parts[2]) != run_id:
        raise ValueError(f"{label}.run_url must contain run_id")
    publication_parts = github_url(
        mapping[publication_key], f"{label}.{publication_key}", publication_pattern
    )
    same_repository(publication_parts, repository, f"{label}.{publication_key}")
    timeline = ordered_timestamps(
        mapping,
        [
            "workflow_failed_at",
            "webhook_recorded_at",
            "analysis_started_at",
            "analysis_completed_at",
            "published_at",
        ],
        label,
    )
    result: dict[str, Any] = {
        "run_id": run_id,
        "run_url": mapping["run_url"],
        "workflow_conclusion": safe_identifier(
            mapping["workflow_conclusion"], f"{label}.workflow_conclusion"
        ),
        publication_key: mapping[publication_key],
        "timeline": {key: utc_timestamp(timestamp) for key, timestamp in timeline.items()},
        "start_seconds": duration_seconds(
            timeline["webhook_recorded_at"], timeline["analysis_started_at"]
        ),
        "completion_seconds": duration_seconds(
            timeline["webhook_recorded_at"], timeline["analysis_completed_at"]
        ),
    }
    if publication_key == "comment_url":
        pull_request_number = positive_int(
            mapping["pull_request_number"], f"{label}.pull_request_number"
        )
        if int(publication_parts[2]) != pull_request_number:
            raise ValueError(f"{label}.comment_url must contain pull_request_number")
        result.update(
            {
                "pull_request_number": pull_request_number,
                "evidence_present": require_bool(
                    mapping["evidence_present"], f"{label}.evidence_present"
                ),
                "related_files_present": require_bool(
                    mapping["related_files_present"], f"{label}.related_files_present"
                ),
                "run_link_present": require_bool(
                    mapping["run_link_present"], f"{label}.run_link_present"
                ),
            }
        )
    return result


def parse_redelivery_item(
    value: Any,
    label: str,
    repository: tuple[str, str],
    pattern: re.Pattern[str],
) -> dict[str, Any]:
    mapping = require_mapping(value, label)
    require_exact_keys(
        mapping,
        {"initial_url", "redelivery_url", "count_before", "count_after", "redelivered_at"},
        label,
    )
    initial_parts = github_url(mapping["initial_url"], f"{label}.initial_url", pattern)
    redelivery_parts = github_url(
        mapping["redelivery_url"], f"{label}.redelivery_url", pattern
    )
    same_repository(initial_parts, repository, f"{label}.initial_url")
    same_repository(redelivery_parts, repository, f"{label}.redelivery_url")
    return {
        "initial_url": mapping["initial_url"],
        "redelivery_url": mapping["redelivery_url"],
        "count_before": non_negative_int(mapping["count_before"], f"{label}.count_before"),
        "count_after": non_negative_int(mapping["count_after"], f"{label}.count_after"),
        "redelivered_at": utc_timestamp(
            parse_timestamp(mapping["redelivered_at"], f"{label}.redelivered_at")
        ),
    }


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


def compile_evidence(
    observation: Mapping[str, Any],
    input_sha256: str,
    *,
    max_start_seconds: float,
    max_completion_seconds: float,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    require_exact_keys(observation, TOP_LEVEL_KEYS, "observation")
    if observation["schema_version"] != 1:
        raise ValueError("observation.schema_version must be 1")
    if any(
        not math.isfinite(threshold) or threshold < 0
        for threshold in (max_start_seconds, max_completion_seconds)
    ):
        raise ValueError("thresholds must be non-negative finite numbers")

    acceptance_id = safe_identifier(observation["acceptance_id"], "acceptance_id")
    source_revision = safe_identifier(observation["source_revision"], "source_revision")
    environment = safe_identifier(observation["environment"], "environment")
    repository_parts = github_url(
        observation["repository_url"], "repository_url", REPOSITORY_PATH
    )
    repository = (repository_parts[0], repository_parts[1])
    installation_id = positive_int(observation["installation_id"], "installation_id")

    permissions = require_mapping(observation["permissions"], "permissions")
    require_exact_keys(permissions, set(EXPECTED_PERMISSIONS), "permissions")
    if not all(isinstance(value, str) for value in permissions.values()):
        raise ValueError("permissions values must be strings")

    started_at = parse_timestamp(observation["started_at"], "started_at")
    completed_at = parse_timestamp(observation["completed_at"], "completed_at")
    if completed_at <= started_at:
        raise ValueError("completed_at must follow started_at")

    pr_run = parse_run(
        observation["pr_run"], "pr_run", repository,
        publication_key="comment_url", publication_pattern=COMMENT_PATH,
    )
    branch_run = parse_run(
        observation["branch_run"], "branch_run", repository,
        publication_key="check_url", publication_pattern=CHECK_PATH,
    )
    if pr_run["run_id"] == branch_run["run_id"]:
        raise ValueError("pr_run and branch_run must use different run IDs")

    redelivery = require_mapping(observation["redelivery"], "redelivery")
    require_exact_keys(redelivery, {"pr_comment", "branch_check"}, "redelivery")
    pr_redelivery = parse_redelivery_item(
        redelivery["pr_comment"], "redelivery.pr_comment", repository, COMMENT_PATH
    )
    branch_redelivery = parse_redelivery_item(
        redelivery["branch_check"], "redelivery.branch_check", repository, CHECK_PATH
    )
    if pr_redelivery["initial_url"] != pr_run["comment_url"]:
        raise ValueError("redelivery.pr_comment.initial_url must match pr_run.comment_url")
    if branch_redelivery["initial_url"] != branch_run["check_url"]:
        raise ValueError("redelivery.branch_check.initial_url must match branch_run.check_url")

    secret_scan = require_mapping(observation["seeded_secret_scan"], "seeded_secret_scan")
    require_exact_keys(
        secret_scan,
        {
            "seeded_secret_sha256",
            "published_matches",
            "persistence_matches",
            "provider_request_matches",
            "checked_at",
        },
        "seeded_secret_scan",
    )
    fingerprint = secret_scan["seeded_secret_sha256"]
    if not isinstance(fingerprint, str) or SHA256.fullmatch(fingerprint) is None:
        raise ValueError("seeded_secret_scan.seeded_secret_sha256 must be lowercase SHA-256")
    scan_counts = {
        key: non_negative_int(secret_scan[key], f"seeded_secret_scan.{key}")
        for key in ("published_matches", "persistence_matches", "provider_request_matches")
    }
    scan_checked_at = parse_timestamp(secret_scan["checked_at"], "seeded_secret_scan.checked_at")

    fork = require_mapping(observation["external_fork"], "external_fork")
    require_exact_keys(
        fork,
        {
            "run_id", "run_url", "pull_request_number", "webhook_recorded_at",
            "processed_at", "warning_comment_url", "llm_invocations",
            "commit_check_publications",
        },
        "external_fork",
    )
    fork_run_id = positive_int(fork["run_id"], "external_fork.run_id")
    fork_run_parts = github_url(fork["run_url"], "external_fork.run_url", RUN_PATH)
    same_repository(fork_run_parts, repository, "external_fork.run_url")
    if int(fork_run_parts[2]) != fork_run_id:
        raise ValueError("external_fork.run_url must contain run_id")
    fork_pr_number = positive_int(
        fork["pull_request_number"], "external_fork.pull_request_number"
    )
    warning_parts = github_url(
        fork["warning_comment_url"], "external_fork.warning_comment_url", COMMENT_PATH
    )
    same_repository(warning_parts, repository, "external_fork.warning_comment_url")
    if int(warning_parts[2]) != fork_pr_number:
        raise ValueError("external_fork.warning_comment_url must contain pull_request_number")
    fork_timeline = ordered_timestamps(
        fork, ["webhook_recorded_at", "processed_at"], "external_fork"
    )
    fork_llm_invocations = non_negative_int(
        fork["llm_invocations"], "external_fork.llm_invocations"
    )
    fork_check_publications = non_negative_int(
        fork["commit_check_publications"], "external_fork.commit_check_publications"
    )

    pr_redelivered_at = parse_timestamp(
        pr_redelivery["redelivered_at"], "redelivery.pr_comment.redelivered_at"
    )
    branch_redelivered_at = parse_timestamp(
        branch_redelivery["redelivered_at"], "redelivery.branch_check.redelivered_at"
    )
    if pr_redelivered_at < parse_timestamp(
        pr_run["timeline"]["published_at"], "pr_run.published_at"
    ):
        raise ValueError("PR redelivery must follow initial publication")
    if branch_redelivered_at < parse_timestamp(
        branch_run["timeline"]["published_at"], "branch_run.published_at"
    ):
        raise ValueError("branch redelivery must follow initial publication")
    if scan_checked_at < max(
        pr_redelivered_at, branch_redelivered_at, fork_timeline["processed_at"]
    ):
        raise ValueError("seeded secret scan must follow all publication exercises")

    latest_recorded = max(
        completed_at,
        scan_checked_at,
        fork_timeline["processed_at"],
        pr_redelivered_at,
        branch_redelivered_at,
    )
    now = (checked_at or datetime.now(UTC)).astimezone(UTC)
    if latest_recorded > now:
        raise ValueError("observation must not contain future events")
    for label, run in (("pr_run", pr_run), ("branch_run", branch_run)):
        first = parse_timestamp(run["timeline"]["workflow_failed_at"], label)
        published = parse_timestamp(run["timeline"]["published_at"], label)
        if first < started_at or published > completed_at:
            raise ValueError(f"{label} timeline must be within the acceptance window")
    if fork_timeline["webhook_recorded_at"] < started_at or scan_checked_at > completed_at:
        raise ValueError("security exercises must be within the acceptance window")

    checks = {
        "least_privilege_permissions": dict(permissions) == EXPECTED_PERMISSIONS,
        "pr_workflow_failed": pr_run["workflow_conclusion"] == "failure",
        "branch_workflow_failed": branch_run["workflow_conclusion"] == "failure",
        "pr_start_slo": pr_run["start_seconds"] <= max_start_seconds,
        "pr_completion_slo": pr_run["completion_seconds"] <= max_completion_seconds,
        "branch_start_slo": branch_run["start_seconds"] <= max_start_seconds,
        "branch_completion_slo": branch_run["completion_seconds"] <= max_completion_seconds,
        "pr_content_complete": all(
            pr_run[key]
            for key in ("evidence_present", "related_files_present", "run_link_present")
        ),
        "pr_comment_idempotent": (
            pr_redelivery["initial_url"] == pr_redelivery["redelivery_url"]
            and pr_redelivery["count_before"] == 1
            and pr_redelivery["count_after"] == 1
        ),
        "branch_check_idempotent": (
            branch_redelivery["initial_url"] == branch_redelivery["redelivery_url"]
            and branch_redelivery["count_before"] == 1
            and branch_redelivery["count_after"] == 1
        ),
        "seeded_secret_absent": all(count == 0 for count in scan_counts.values()),
        "external_fork_isolated": fork_llm_invocations == 0 and fork_check_publications == 0,
    }

    return {
        "schema_version": 1,
        "checked_at": utc_timestamp(now),
        "acceptance_id": acceptance_id,
        "source_revision": source_revision,
        "environment": environment,
        "repository_url": observation["repository_url"],
        "installation_id": installation_id,
        "permissions": dict(sorted(permissions.items())),
        "acceptance_window": {
            "started_at": utc_timestamp(started_at),
            "completed_at": utc_timestamp(completed_at),
        },
        "pr_run": pr_run,
        "branch_run": branch_run,
        "redelivery": {"pr_comment": pr_redelivery, "branch_check": branch_redelivery},
        "seeded_secret_scan": {
            "seeded_secret_sha256": fingerprint,
            **scan_counts,
            "checked_at": utc_timestamp(scan_checked_at),
        },
        "external_fork": {
            "run_id": fork_run_id,
            "run_url": fork["run_url"],
            "pull_request_number": fork_pr_number,
            "warning_comment_url": fork["warning_comment_url"],
            "timeline": {
                key: utc_timestamp(timestamp) for key, timestamp in fork_timeline.items()
            },
            "llm_invocations": fork_llm_invocations,
            "commit_check_publications": fork_check_publications,
        },
        "threshold_seconds": {
            "analysis_start": max_start_seconds,
            "analysis_completion": max_completion_seconds,
        },
        "checks": checks,
        "passed": all(checks.values()),
        "input_sha256": input_sha256,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-start-seconds", type=float, default=60)
    parser.add_argument("--max-completion-seconds", type=float, default=120)
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
            max_start_seconds=args.max_start_seconds,
            max_completion_seconds=args.max_completion_seconds,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
