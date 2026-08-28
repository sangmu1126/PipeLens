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
