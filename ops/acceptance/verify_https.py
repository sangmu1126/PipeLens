"""Verify the public HTTPS boundary without recording credentials or cookie values."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx

MINIMUM_HSTS_SECONDS = 31_536_000
SECURITY_HEADERS = {
    "content-security-policy": None,
    "permissions-policy": "camera=(), geolocation=(), microphone=()",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


class AcceptanceError(RuntimeError):
    pass


def validate_origin(value: str, scheme: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != scheme or not parsed.hostname:
        raise AcceptanceError(f"origin must use {scheme} and include a hostname")
    if parsed.username or parsed.password or parsed.path not in ("", "/"):
        raise AcceptanceError("origin must not contain credentials or a path")
    if parsed.query or parsed.fragment:
        raise AcceptanceError("origin must not contain a query or fragment")
    return value.rstrip("/")


def default_http_origin(https_origin: str) -> str:
    parsed = urlsplit(https_origin)
    hostname = parsed.hostname or ""
    authority = f"[{hostname}]" if ":" in hostname else hostname
    return urlunsplit(("http", authority, "", "", ""))


def parse_hsts(value: str) -> dict[str, object]:
    directives = [part.strip() for part in value.split(";") if part.strip()]
    max_age_values = [
        part.split("=", 1)[1]
        for part in directives
        if part.lower().startswith("max-age=")
    ]
    if len(max_age_values) != 1:
        raise AcceptanceError("Strict-Transport-Security must define one max-age")
    try:
        max_age = int(max_age_values[0])
    except ValueError as exc:
        raise AcceptanceError("HSTS max-age must be an integer") from exc
    if max_age < MINIMUM_HSTS_SECONDS:
        raise AcceptanceError(f"HSTS max-age must be at least {MINIMUM_HSTS_SECONDS}")
    lowered = {part.lower() for part in directives}
    return {
        "max_age_seconds": max_age,
        "include_subdomains": "includesubdomains" in lowered,
        "preload": "preload" in lowered,
    }


def verify_https_boundary(
    client: httpx.Client,
    https_origin: str,
    http_origin: str | None = None,
    checked_at: datetime | None = None,
) -> dict[str, object]:
    https_origin = validate_origin(https_origin, "https")
    http_origin = validate_origin(http_origin or default_http_origin(https_origin), "http")

    redirect = client.get(f"{http_origin}/")
    redirect_target = redirect.headers.get("location", "").rstrip("/")
    if redirect.status_code not in (301, 308) or redirect_target != https_origin:
        raise AcceptanceError("HTTP origin must permanently redirect to the exact HTTPS origin")

    dashboard = client.get(f"{https_origin}/")
    if dashboard.status_code != 200:
        raise AcceptanceError(f"dashboard returned HTTP {dashboard.status_code}")
    header_results: dict[str, str] = {}
    for name, expected in SECURITY_HEADERS.items():
        actual = dashboard.headers.get(name)
        if actual is None or (expected is not None and actual != expected):
            raise AcceptanceError(f"dashboard security header is missing or invalid: {name}")
        header_results[name] = "valid"
    hsts = parse_hsts(dashboard.headers.get("strict-transport-security", ""))

    readiness = client.get(f"{https_origin}/readyz")
    try:
        readiness_payload = readiness.json()
    except ValueError as exc:
        raise AcceptanceError("readiness response is not JSON") from exc
    checks = readiness_payload.get("checks", {})
    if (
        readiness.status_code != 200
        or readiness_payload.get("status") != "ready"
        or checks.get("database") != "ok"
        or checks.get("queue") != "ok"
    ):
        raise AcceptanceError("readiness did not report healthy database and queue")

    oauth = client.get(f"{https_origin}/auth/github/login")
    location = urlsplit(oauth.headers.get("location", ""))
    parameters = parse_qs(location.query)
    expected_callback = f"{https_origin}/auth/github/callback"
    if (
        oauth.status_code != 302
        or location.scheme != "https"
        or location.hostname != "github.com"
        or location.path != "/login/oauth/authorize"
        or parameters.get("redirect_uri") != [expected_callback]
        or not parameters.get("state", [""])[0]
    ):
        raise AcceptanceError("OAuth start did not return the expected GitHub redirect")
    state_cookies = [
        value
        for value in oauth.headers.get_list("set-cookie")
        if value.lower().startswith("pipelens_oauth_state=")
    ]
    if len(state_cookies) != 1:
        raise AcceptanceError("OAuth state cookie was not set exactly once")
    cookie = state_cookies[0].lower()
    if not all(flag in cookie for flag in ("; secure", "; httponly", "; samesite=lax")):
        raise AcceptanceError("OAuth state cookie must use Secure, HttpOnly and SameSite=Lax")

    timestamp = checked_at or datetime.now(UTC)
    return {
        "schema_version": 1,
        "checked_at": timestamp.isoformat(),
        "origin": https_origin,
        "result": "pass",
        "tls": {"certificate_verified": True},
        "http_redirect": {"status_code": redirect.status_code, "exact_origin": True},
        "dashboard": {
            "status_code": dashboard.status_code,
            "headers": header_results,
            "hsts": hsts,
        },
        "readiness": {"status_code": readiness.status_code, "status": "ready", "checks": checks},
        "oauth_start": {
            "status_code": oauth.status_code,
            "provider": "github.com",
            "callback_matches": True,
            "state_present": True,
            "state_cookie_flags": {"secure": True, "httponly": True, "samesite": "lax"},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="public HTTPS origin, for example https://pipelens.example")
    parser.add_argument("--http-origin", help="HTTP origin when it differs from the default port")
    parser.add_argument("--output", type=Path, help="write redacted JSON evidence to this path")
    args = parser.parse_args()
    try:
        with httpx.Client(follow_redirects=False, timeout=10) as client:
            evidence = verify_https_boundary(client, args.origin, args.http_origin)
    except (AcceptanceError, httpx.HTTPError) as exc:
        print(f"HTTPS acceptance preflight failed: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
