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


def test_dashboard_server_proxies_github_webhooks_to_api() -> None:
    configuration = Path("frontend/nginx.conf").read_text()

    webhook_location = configuration.split("location /webhooks/ {", 1)[1].split(
        "}", 1
    )[0]

    assert "proxy_pass http://api:8000;" in webhook_location


def test_container_access_logs_do_not_record_query_strings() -> None:
    nginx_configuration = Path("frontend/nginx.conf").read_text()
    api_dockerfile = Path("Dockerfile").read_text()

    log_format = nginx_configuration.split("log_format pipelens", 1)[1].split(";", 1)[0]

    assert "$uri" in log_format
    assert "$request_uri" not in log_format
    assert "$request " not in log_format
    assert "$args" not in log_format
    assert "$query_string" not in log_format
    assert "$http_referer" not in log_format
    assert "access_log /var/log/nginx/access.log pipelens;" in nginx_configuration
    assert '"--no-access-log"' in api_dockerfile
