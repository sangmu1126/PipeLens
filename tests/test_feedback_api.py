from pathlib import Path

from fastapi.testclient import TestClient

from pipelens.config import Settings
from pipelens.main import create_app
from pipelens.models import AnalysisRecord


def test_feedback_endpoint_updates_analysis_and_metrics(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=str(tmp_path / "db.sqlite"), auth_required=False))

    with TestClient(app) as client:
        app.state.store.create_if_absent(
            AnalysisRecord(
                run_id=501,
                delivery_id="delivery-501",
                repository="acme/widgets",
                workflow_name="CI",
                head_sha="abc123",
                html_url="https://github.com/acme/widgets/actions/runs/501",
            )
        )
        response = client.put(
            "/api/analyses/501/feedback",
            json={"accuracy": "accurate", "suggestion_resolved": True},
        )
        detail = client.get("/api/analyses/501")
        metrics = client.get("/metrics")

    assert response.status_code == 200
    assert detail.json()["feedback"]["accuracy"] == "accurate"
    assert detail.json()["feedback"]["suggestion_resolved"] is True
    assert 'pipelens_feedback_total{dimension="accuracy",value="accurate"} 1.0' in metrics.text


def test_feedback_endpoint_validates_input_and_run(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=str(tmp_path / "db.sqlite"), auth_required=False))

    with TestClient(app) as client:
        invalid = client.put("/api/analyses/999/feedback", json={})
        missing = client.put("/api/analyses/999/feedback", json={"accuracy": "inaccurate"})

    assert invalid.status_code == 422
    assert missing.status_code == 404
