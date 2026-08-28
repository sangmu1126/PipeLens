import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from pipelens.config import Settings
from pipelens.main import create_app
from pipelens.models import AnalysisRecord
from pipelens.store import AnalysisStore


def _signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _failure_payload() -> dict:
    return {
        "action": "completed",
        "installation": {"id": 99},
        "repository": {"full_name": "acme/widgets"},
        "workflow_run": {
            "id": 1234,
            "name": "CI",
            "conclusion": "failure",
            "head_sha": "abc123",
            "html_url": "https://github.com/acme/widgets/actions/runs/1234",
        },
    }


def test_webhook_rejects_bad_signature(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            webhook_secret="secret",
            database_path=str(tmp_path / "db.sqlite"),
            auth_required=False,
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/github",
            content=b"{}",
            headers={
                "X-GitHub-Event": "workflow_run",
                "X-GitHub-Delivery": "delivery-1",
                "X-Hub-Signature-256": "sha256=bad",
            },
        )

    assert response.status_code == 401


def test_webhook_accepts_failure_once(tmp_path: Path) -> None:
    settings = Settings(
        webhook_secret="secret", database_path=str(tmp_path / "db.sqlite"), auth_required=False
    )
    app = create_app(settings)
    app.state.queue.enqueue = AsyncMock(side_effect=[True, False])
    body = json.dumps(_failure_payload()).encode()
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "workflow_run",
        "X-GitHub-Delivery": "delivery-1",
        "X-Hub-Signature-256": _signature(body, settings.webhook_secret),
    }

    with TestClient(app) as client:
        first = client.post("/webhooks/github", content=body, headers=headers)
        second = client.post("/webhooks/github", content=body, headers=headers)
        detail = client.get("/api/analyses/1234")
        metrics = client.get("/metrics")

    assert first.status_code == 202
    assert first.json() == {"accepted": True, "run_id": 1234}
    assert second.json() == {"accepted": False, "run_id": 1234}
    assert detail.status_code == 200
    assert detail.json()["repository"] == "acme/widgets"
    assert metrics.status_code == 200
    assert 'pipelens_webhooks_total{outcome="accepted"} 1.0' in metrics.text
    assert 'pipelens_webhooks_total{outcome="duplicate"} 1.0' in metrics.text
    assert app.state.queue.enqueue.await_count == 2


def test_webhook_retry_recovers_database_queue_gap(tmp_path: Path) -> None:
    settings = Settings(
        webhook_secret="secret", database_path=str(tmp_path / "db.sqlite"), auth_required=False
    )
    app = create_app(settings)
    app.state.queue.enqueue = AsyncMock(side_effect=[RuntimeError("queue down"), True])
    body = json.dumps(_failure_payload()).encode()
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "workflow_run",
        "X-GitHub-Delivery": "delivery-gap",
        "X-Hub-Signature-256": _signature(body, settings.webhook_secret),
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        failed = client.post("/webhooks/github", content=body, headers=headers)
        recovered = client.post("/webhooks/github", content=body, headers=headers)
        metrics = client.get("/metrics")

    assert failed.status_code == 503
    assert recovered.json() == {"accepted": True, "run_id": 1234}
    assert 'pipelens_webhooks_total{outcome="queue_error"} 1.0' in metrics.text
    assert 'pipelens_webhooks_total{outcome="recovered"} 1.0' in metrics.text


def test_startup_reconciles_queued_database_records(tmp_path: Path) -> None:
    database_path = str(tmp_path / "db.sqlite")
    store = AnalysisStore(database_path)
    store.initialize()
    store.create_if_absent(
        AnalysisRecord(
            run_id=222,
            delivery_id="delivery-222",
            repository="acme/widgets",
            workflow_name="CI",
            head_sha="def456",
            html_url="https://github.com/acme/widgets/actions/runs/222",
            installation_id=99,
        )
    )
    store.close()
    app = create_app(Settings(database_path=database_path, auth_required=False))
    app.state.queue.enqueue = AsyncMock(return_value=True)

    with TestClient(app) as client:
        metrics = client.get("/metrics")

    queued_request = app.state.queue.enqueue.await_args.args[0]
    assert queued_request.run_id == 222
    assert "pipelens_queue_reconciled_total 1.0" in metrics.text


def test_webhook_ignores_successful_run(tmp_path: Path) -> None:
    settings = Settings(
        webhook_secret="secret", database_path=str(tmp_path / "db.sqlite"), auth_required=False
    )
    app = create_app(settings)
    payload = _failure_payload()
    payload["workflow_run"]["conclusion"] = "success"
    body = json.dumps(payload).encode()

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_run",
                "X-GitHub-Delivery": "delivery-2",
                "X-Hub-Signature-256": _signature(body, settings.webhook_secret),
            },
        )

    assert response.status_code == 204
