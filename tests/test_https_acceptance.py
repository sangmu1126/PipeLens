from datetime import UTC, datetime

import httpx
import pytest

from ops.acceptance.verify_https import AcceptanceError, validate_origin, verify_https_boundary

ORIGIN = "https://pipelens.example"


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.scheme == "http":
        return httpx.Response(308, headers={"Location": f"{ORIGIN}/"})
    if request.url.path == "/":
        return httpx.Response(
            200,
            headers={
                "Content-Security-Policy": "default-src 'self'",
                "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
                "Referrer-Policy": "no-referrer",
                "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
            },
        )
    if request.url.path == "/readyz":
        return httpx.Response(
            200,
            json={"status": "ready", "checks": {"database": "ok", "queue": "ok"}},
        )
    if request.url.path == "/auth/github/login":
        callback = httpx.URL("https://github.com/login/oauth/authorize").copy_add_param(
            "redirect_uri", f"{ORIGIN}/auth/github/callback"
        ).copy_add_param("state", "redacted-state")
        return httpx.Response(
            302,
            headers={
                "Location": str(callback),
                "Set-Cookie": (
                    "pipelens_oauth_state=secret; Path=/; Secure; HttpOnly; SameSite=lax"
                ),
            },
        )
    return httpx.Response(404)


def test_https_boundary_returns_redacted_machine_readable_evidence() -> None:
    checked_at = datetime(2026, 9, 1, 5, 0, tzinfo=UTC)
    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        evidence = verify_https_boundary(client, ORIGIN, checked_at=checked_at)

    assert evidence["result"] == "pass"
    assert evidence["checked_at"] == "2026-09-01T05:00:00+00:00"
    assert evidence["dashboard"]["hsts"]["max_age_seconds"] == 31_536_000
    assert evidence["readiness"]["checks"] == {"database": "ok", "queue": "ok"}
    assert "redacted-state" not in str(evidence)
    assert "secret" not in str(evidence)


@pytest.mark.parametrize(
    "origin",
    [
        "http://pipelens.example",
        "https://user:password@pipelens.example",
        "https://pipelens.example/app",
        "https://pipelens.example?debug=true",
    ],
)
def test_https_origin_rejects_unsafe_or_non_origin_values(origin: str) -> None:
    with pytest.raises(AcceptanceError):
        validate_origin(origin, "https")


def test_https_boundary_rejects_short_hsts_policy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response = _handler(request)
        if request.url.path == "/" and request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=300"
        return response

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(AcceptanceError, match="HSTS max-age"),
    ):
        verify_https_boundary(client, ORIGIN)


def test_https_boundary_rejects_oauth_redirect_without_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/github/login":
            return httpx.Response(
                302,
                headers={
                    "Location": (
                        "https://github.com/login/oauth/authorize"
                        f"?redirect_uri={ORIGIN}/auth/github/callback"
                    ),
                    "Set-Cookie": (
                        "pipelens_oauth_state=secret; Path=/; Secure; HttpOnly; SameSite=lax"
                    ),
                },
            )
        return _handler(request)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(AcceptanceError, match="OAuth start"),
    ):
        verify_https_boundary(client, ORIGIN)
