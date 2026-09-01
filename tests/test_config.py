from pathlib import Path

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


def test_token_encryption_key_ring_deduplicates_and_ignores_empty_values() -> None:
    settings = Settings(
        token_encryption_key="primary",
        token_encryption_fallback_keys=" fallback, primary, ,older ",
    )

    assert settings.token_encryption_key_ring == ["primary", "fallback", "older"]


@pytest.mark.parametrize(
    ("value_name", "file_name", "content"),
    [
        ("webhook_secret", "webhook_secret_file", "webhook-value"),
        ("github_private_key", "github_private_key_file", "key-line-1\nkey-line-2"),
        ("github_client_secret", "github_client_secret_file", "client-value"),
        ("session_secret", "session_secret_file", "session-value"),
        ("token_encryption_key", "token_encryption_key_file", "primary-key"),
        (
            "token_encryption_fallback_keys",
            "token_encryption_fallback_keys_file",
            "fallback-1,fallback-2",
        ),
        ("openai_api_key", "openai_api_key_file", "provider-value"),
        ("database_url", "database_url_file", "postgresql+psycopg://service@db/app"),
        ("redis_url", "redis_url_file", "redis://service@queue/0"),
    ],
)
def test_secret_settings_support_read_only_file_injection(
    tmp_path: Path, value_name: str, file_name: str, content: str
) -> None:
    secret_file = tmp_path / file_name
    secret_file.write_text(f"{content}\n", encoding="utf-8")

    settings = Settings(**{file_name: secret_file})

    assert getattr(settings, value_name) == content


def test_secret_file_setting_loads_from_environment(tmp_path: Path, monkeypatch) -> None:
    secret_file = tmp_path / "webhook"
    secret_file.write_text("mounted-secret\n", encoding="utf-8")
    monkeypatch.setenv("PIPELENS_WEBHOOK_SECRET_FILE", str(secret_file))

    settings = Settings(_env_file=None)

    assert settings.webhook_secret == "mounted-secret"


def test_production_validation_uses_file_injected_secrets(tmp_path: Path) -> None:
    secret_files: dict[str, Path] = {}
    for name, value in {
        "webhook_secret_file": "w" * 32,
        "session_secret_file": "s" * 32,
        "token_encryption_key_file": "encryption-key",
    }.items():
        secret_file = tmp_path / name
        secret_file.write_text(value, encoding="utf-8")
        secret_files[name] = secret_file

    settings = Settings(
        environment="production",
        public_url="https://pipelens.example.com",
        session_cookie_secure=True,
        **secret_files,
    )

    assert settings.webhook_secret == "w" * 32
    assert settings.session_secret == "s" * 32
    assert settings.token_encryption_key == "encryption-key"


def test_secret_value_and_file_are_mutually_exclusive(tmp_path: Path) -> None:
    secret_file = tmp_path / "webhook"
    secret_file.write_text("mounted-secret", encoding="utf-8")

    with pytest.raises(ValidationError, match="WEBHOOK_SECRET.*WEBHOOK_SECRET_FILE conflict"):
        Settings(webhook_secret="direct-secret", webhook_secret_file=secret_file)


@pytest.mark.parametrize("content", [b"", b"\xff"])
def test_secret_file_rejects_empty_or_non_utf8_content(tmp_path: Path, content: bytes) -> None:
    secret_file = tmp_path / "webhook"
    secret_file.write_bytes(content)

    with pytest.raises(ValidationError, match="WEBHOOK_SECRET_FILE must"):
        Settings(webhook_secret_file=secret_file)


def test_secret_file_rejects_non_regular_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="WEBHOOK_SECRET_FILE must reference a regular file"):
        Settings(webhook_secret_file=tmp_path)


def test_secret_file_rejects_files_larger_than_one_megabyte(tmp_path: Path) -> None:
    secret_file = tmp_path / "webhook"
    secret_file.write_bytes(b"x" * (1024 * 1024 + 1))

    with pytest.raises(ValidationError, match="WEBHOOK_SECRET_FILE must not exceed 1048576 bytes"):
        Settings(webhook_secret_file=secret_file)
