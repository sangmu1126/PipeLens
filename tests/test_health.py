from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from pipelens.config import Settings
from pipelens.main import create_app


def _app(tmp_path: Path):
    return create_app(
        Settings(database_path=str(tmp_path / "db.sqlite"), auth_required=False)
    )


def test_liveness_does_not_depend_on_database_or_queue(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.state.store.healthcheck = MagicMock(side_effect=RuntimeError("database down"))
    app.state.queue.healthcheck = AsyncMock(side_effect=RuntimeError("queue down"))

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    app.state.store.healthcheck.assert_not_called()
    app.state.queue.healthcheck.assert_not_awaited()


def test_readiness_checks_database_and_queue(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.state.store.healthcheck = MagicMock()
    app.state.queue.healthcheck = AsyncMock()

    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "queue": "ok"},
    }
    app.state.store.healthcheck.assert_called_once_with()
    app.state.queue.healthcheck.assert_awaited_once_with()


def test_readiness_reports_each_unavailable_dependency(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.state.store.healthcheck = MagicMock(side_effect=RuntimeError("database down"))
    app.state.queue.healthcheck = AsyncMock(side_effect=RuntimeError("queue down"))

    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "unavailable", "queue": "unavailable"},
    }
