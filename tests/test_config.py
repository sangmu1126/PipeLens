import pytest
from pydantic import ValidationError

from pipelens.config import Settings


def test_worker_heartbeat_must_be_shorter_than_lease() -> None:
    with pytest.raises(ValidationError, match="heartbeat must be positive and shorter"):
        Settings(worker_lease_seconds=10, worker_heartbeat_seconds=10)


def test_worker_lease_settings_accept_safe_interval() -> None:
    settings = Settings(worker_lease_seconds=60, worker_heartbeat_seconds=15)

    assert settings.worker_lease_seconds == 60
    assert settings.worker_heartbeat_seconds == 15


def test_analysis_slo_thresholds_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="SLO thresholds must be positive"):
        Settings(analysis_start_slo_seconds=0)


def _production_settings(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "environment": "production",
        "public_url": "https://pipelens.example.com",
        "session_cookie_secure": True,
        "webhook_secret": "w" * 32,
        "session_secret": "s" * 32,
        "token_encryption_key": "encryption-key",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"public_url": "http://pipelens.example.com"}, "public URL must use HTTPS"),
        ({"public_url": "https:not-a-host"}, "public URL must use HTTPS"),
        ({"auth_required": False}, "authentication must be required"),
        ({"session_cookie_secure": False}, "session cookies must be secure"),
        ({"webhook_secret": "short"}, "webhook secret must be at least 32"),
        ({"session_secret": "short"}, "session secret must be at least 32"),
        ({"token_encryption_key": None}, "token encryption key must be configured"),
    ],
)
def test_production_rejects_unsafe_security_settings(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(**_production_settings(**override))


def test_production_accepts_explicit_security_settings() -> None:
    settings = Settings(**_production_settings())

    assert settings.environment == "production"
