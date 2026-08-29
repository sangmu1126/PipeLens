import hashlib
import hmac
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pipelens.config import Settings
from pipelens.main import create_app
from pipelens.security import InvalidSignatureError, verify_github_signature


def test_verify_github_signature() -> None:
    body = b'{"action":"completed"}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    verify_github_signature(body, signature, "secret")


def test_verify_github_signature_rejects_invalid_value() -> None:
    with pytest.raises(InvalidSignatureError):
        verify_github_signature(b"payload", "sha256=bad", "secret")


def test_api_responses_include_security_headers(tmp_path: Path) -> None:
    app = create_app(
        Settings(database_path=str(tmp_path / "security.db"), auth_required=False)
    )

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "camera=(), geolocation=(), microphone=()"


def test_dashboard_server_defines_security_headers() -> None:
    configuration = Path("frontend/nginx.conf").read_text()

    for header in (
        "Content-Security-Policy",
        "Permissions-Policy",
        "Referrer-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
    ):
        assert f"add_header {header}" in configuration
