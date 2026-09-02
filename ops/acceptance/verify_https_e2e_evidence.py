"""Validate redacted evidence from a real HTTPS OAuth and webhook acceptance run."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
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
DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
TOP_LEVEL_KEYS = {
    "schema_version",
    "acceptance_id",
    "source_revision",
    "environment",
    "origin",
    "started_at",
    "completed_at",
    "preflight",
    "configured_urls",
    "browser_flow",
    "forwarding",
    "webhook",
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


def require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def safe_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or "://" in value or not SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a non-secret identifier of at most 200 characters")
    return value


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
    parsed = {key: parse_timestamp(value[key], f"{label}.{key}") for key in keys}
    if any(left > right for left, right in pairwise(parsed.values())):
        raise ValueError(f"{label} timestamps must be chronological")
    return parsed


def utc_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def public_https_origin(value: Any, label: str = "origin") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a public HTTPS origin")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"{label} contains an invalid port") from error
    hostname = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} must be a credential-free HTTPS origin")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        labels = hostname.rstrip(".").split(".")
        if (
            len(labels) < 2
            or hostname.endswith(".local")
            or any(DNS_LABEL.fullmatch(item) is None for item in labels)
        ):
            raise ValueError(f"{label} must use a public DNS hostname") from None
    else:
        raise ValueError(f"{label} must use a public DNS hostname")
    authority = hostname.lower() + (f":{port}" if port is not None else "")
    return f"https://{authority}"


def same_origin_url(value: Any, origin: str, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an HTTPS URL")
    parsed = urlsplit(value)
    origin_parts = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != origin_parts.netloc.lower()
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} must be a credential-free URL on origin")
    return value


def parse_cookie(value: Any, label: str) -> dict[str, Any]:
    mapping = require_mapping(value, label)
    require_exact_keys(mapping, {"secure", "httponly", "samesite"}, label)
    samesite = safe_identifier(mapping["samesite"], f"{label}.samesite").lower()
    return {
        "secure": require_bool(mapping["secure"], f"{label}.secure"),
        "httponly": require_bool(mapping["httponly"], f"{label}.httponly"),
        "samesite": samesite,
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
    max_webhook_response_seconds: float,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    require_exact_keys(observation, TOP_LEVEL_KEYS, "observation")
    if observation["schema_version"] != 1:
        raise ValueError("observation.schema_version must be 1")
    if not math.isfinite(max_webhook_response_seconds) or max_webhook_response_seconds < 0:
        raise ValueError("threshold must be a non-negative finite number")

    acceptance_id = safe_identifier(observation["acceptance_id"], "acceptance_id")
    source_revision = safe_identifier(observation["source_revision"], "source_revision")
    environment = safe_identifier(observation["environment"], "environment")
    origin = public_https_origin(observation["origin"])
    started_at = parse_timestamp(observation["started_at"], "started_at")
    completed_at = parse_timestamp(observation["completed_at"], "completed_at")
    if completed_at <= started_at:
        raise ValueError("completed_at must follow started_at")

    preflight = require_mapping(observation["preflight"], "preflight")
    require_exact_keys(
        preflight, {"evidence_sha256", "checked_at", "origin", "passed"}, "preflight"
    )
    preflight_hash = sha256_value(preflight["evidence_sha256"], "preflight.evidence_sha256")
    preflight_checked_at = parse_timestamp(preflight["checked_at"], "preflight.checked_at")
    preflight_origin = public_https_origin(preflight["origin"], "preflight.origin")
    preflight_passed = require_bool(preflight["passed"], "preflight.passed")

    configured = require_mapping(observation["configured_urls"], "configured_urls")
    require_exact_keys(configured, {"oauth_callback", "setup", "webhook"}, "configured_urls")
    configured_urls = {
        key: same_origin_url(configured[key], origin, f"configured_urls.{key}")
        for key in ("oauth_callback", "setup", "webhook")
    }
    expected_urls = {
        "oauth_callback": f"{origin}/auth/github/callback",
        "setup": f"{origin}/github/setup",
        "webhook": f"{origin}/webhooks/github",
    }

    browser = require_mapping(observation["browser_flow"], "browser_flow")
    require_exact_keys(
        browser,
        {
            "started_at",
            "oauth_authorized_at",
            "installation_selected_at",
            "dashboard_loaded_at",
            "logout_completed_at",
            "captured_at",
            "installation_count",
            "oauth_state_cookie",
            "session_cookie",
            "session_invalid_after_logout",
            "screenshot_evidence_sha256",
        },
        "browser_flow",
    )
    browser_timeline = ordered_timestamps(
        browser,
        [
            "started_at",
            "oauth_authorized_at",
            "installation_selected_at",
            "dashboard_loaded_at",
            "logout_completed_at",
            "captured_at",
        ],
        "browser_flow",
    )
    installation_count = non_negative_int(
        browser["installation_count"], "browser_flow.installation_count"
    )
    state_cookie = parse_cookie(browser["oauth_state_cookie"], "browser_flow.oauth_state_cookie")
    session_cookie = parse_cookie(browser["session_cookie"], "browser_flow.session_cookie")
    session_invalid = require_bool(
        browser["session_invalid_after_logout"], "browser_flow.session_invalid_after_logout"
    )
    screenshot_hash = sha256_value(
        browser["screenshot_evidence_sha256"],
        "browser_flow.screenshot_evidence_sha256",
    )

    forwarding = require_mapping(observation["forwarding"], "forwarding")
    require_exact_keys(
        forwarding,
        {
            "checked_at",
            "observed_scheme",
            "observed_host",
            "application_origin",
            "oauth_redirect_uri",
            "request_evidence_sha256",
        },
        "forwarding",
    )
    forwarding_checked_at = parse_timestamp(forwarding["checked_at"], "forwarding.checked_at")
    observed_scheme = safe_identifier(
        forwarding["observed_scheme"], "forwarding.observed_scheme"
    ).lower()
    observed_host = safe_identifier(forwarding["observed_host"], "forwarding.observed_host").lower()
    application_origin = public_https_origin(
        forwarding["application_origin"], "forwarding.application_origin"
    )
    oauth_redirect_uri = same_origin_url(
        forwarding["oauth_redirect_uri"], origin, "forwarding.oauth_redirect_uri"
    )
    forwarding_hash = sha256_value(
        forwarding["request_evidence_sha256"], "forwarding.request_evidence_sha256"
    )

    webhook = require_mapping(observation["webhook"], "webhook")
    require_exact_keys(
        webhook,
        {
            "event",
            "action",
            "delivery_id_sha256",
            "received_at",
            "signature_verified_at",
            "persisted_at",
            "responded_at",
            "signature_valid",
            "response_status_code",
            "request_evidence_sha256",
        },
        "webhook",
    )
    event = safe_identifier(webhook["event"], "webhook.event")
    action = safe_identifier(webhook["action"], "webhook.action")
    delivery_hash = sha256_value(webhook["delivery_id_sha256"], "webhook.delivery_id_sha256")
    webhook_hash = sha256_value(
        webhook["request_evidence_sha256"], "webhook.request_evidence_sha256"
    )
    webhook_timeline = ordered_timestamps(
        webhook,
        ["received_at", "signature_verified_at", "persisted_at", "responded_at"],
        "webhook",
    )
    signature_valid = require_bool(webhook["signature_valid"], "webhook.signature_valid")
    response_status = non_negative_int(
        webhook["response_status_code"], "webhook.response_status_code"
    )
    webhook_response_seconds = round(
        (webhook_timeline["responded_at"] - webhook_timeline["received_at"]).total_seconds(),
        3,
    )

    if (
        preflight_checked_at < started_at
        or preflight_checked_at > browser_timeline["started_at"]
        or browser_timeline["captured_at"] > completed_at
    ):
        raise ValueError("preflight and browser events must be within the acceptance window")
    if (
        forwarding_checked_at < browser_timeline["started_at"]
        or forwarding_checked_at > browser_timeline["dashboard_loaded_at"]
        or webhook_timeline["received_at"] < started_at
        or webhook_timeline["responded_at"] > completed_at
    ):
        raise ValueError("forwarding and webhook events must be within the acceptance window")
    now = (checked_at or datetime.now(UTC)).astimezone(UTC)
    if completed_at > now:
        raise ValueError("observation must not contain future events")

    origin_parts = urlsplit(origin)
    expected_host = origin_parts.netloc.lower()
    cookie_security = all(
        cookie["secure"] and cookie["httponly"] and cookie["samesite"] == "lax"
        for cookie in (state_cookie, session_cookie)
    )
    checks = {
        "preflight_passed": preflight_passed and preflight_origin == origin,
        "configured_urls_exact": configured_urls == expected_urls,
        "browser_flow_complete": installation_count > 0 and session_invalid,
        "cookie_security": cookie_security,
        "forwarding_exact": (
            observed_scheme == "https"
            and observed_host == expected_host
            and application_origin == origin
            and oauth_redirect_uri == expected_urls["oauth_callback"]
        ),
        "signed_workflow_webhook": (
            event == "workflow_run"
            and action == "completed"
            and signature_valid
            and response_status == 202
        ),
        "webhook_response_slo": webhook_response_seconds <= max_webhook_response_seconds,
    }

    return {
        "schema_version": 1,
        "checked_at": utc_timestamp(now),
        "acceptance_id": acceptance_id,
        "source_revision": source_revision,
        "environment": environment,
        "origin": origin,
        "acceptance_window": {
            "started_at": utc_timestamp(started_at),
            "completed_at": utc_timestamp(completed_at),
        },
        "preflight": {
            "evidence_sha256": preflight_hash,
            "checked_at": utc_timestamp(preflight_checked_at),
            "origin": preflight_origin,
            "passed": preflight_passed,
        },
        "configured_urls": configured_urls,
        "browser_flow": {
            "timeline": {
                key: utc_timestamp(timestamp) for key, timestamp in browser_timeline.items()
            },
            "installation_count": installation_count,
            "oauth_state_cookie": state_cookie,
            "session_cookie": session_cookie,
            "session_invalid_after_logout": session_invalid,
            "screenshot_evidence_sha256": screenshot_hash,
        },
        "forwarding": {
            "checked_at": utc_timestamp(forwarding_checked_at),
            "observed_scheme": observed_scheme,
            "observed_host": observed_host,
            "application_origin": application_origin,
            "oauth_redirect_uri": oauth_redirect_uri,
            "request_evidence_sha256": forwarding_hash,
        },
        "webhook": {
            "event": event,
            "action": action,
            "delivery_id_sha256": delivery_hash,
            "timeline": {
                key: utc_timestamp(timestamp) for key, timestamp in webhook_timeline.items()
            },
            "signature_valid": signature_valid,
            "response_status_code": response_status,
            "response_seconds": webhook_response_seconds,
            "request_evidence_sha256": webhook_hash,
        },
        "threshold_seconds": {"webhook_response": max_webhook_response_seconds},
        "checks": checks,
        "passed": all(checks.values()),
        "input_sha256": input_sha256,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-webhook-response-seconds", type=float, default=10)
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
            max_webhook_response_seconds=args.max_webhook_response_seconds,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
