from pathlib import Path

from fastapi.testclient import TestClient

from pipelens.config import Settings
from pipelens.main import create_app
from pipelens.models import (
    AnalysisRecord,
    AnalysisStatus,
    Classification,
    ErrorCategory,
)


def test_analysis_list_filters_and_validates_query_values(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=str(tmp_path / "db.sqlite"), auth_required=False))

    with TestClient(app) as client:
        for run_id, repository, status, category in [
            (701, "acme/api", AnalysisStatus.COMPLETED, ErrorCategory.TEST),
            (702, "acme/web", AnalysisStatus.FAILED, ErrorCategory.BUILD),
        ]:
            app.state.store.create_if_absent(
                AnalysisRecord(
                    run_id=run_id,
                    delivery_id=f"delivery-{run_id}",
                    repository=repository,
                    workflow_name="CI",
                    head_sha=f"sha-{run_id}",
                    html_url=f"https://github.com/{repository}/actions/runs/{run_id}",
                )
            )
            app.state.store.update(
                run_id,
                status,
                classification=Classification(
                    category=category,
                    confidence=0.9,
                    first_error="failed",
                ),
            )

        filtered = client.get(
            "/api/analyses",
            params={
                "repository": "acme/api",
                "status": "completed",
                "category": "test_failure",
            },
        )
        invalid_status = client.get("/api/analyses", params={"status": "unknown"})
        invalid_category = client.get("/api/analyses", params={"category": "network"})

    assert filtered.status_code == 200
    assert [record["run_id"] for record in filtered.json()] == [701]
    assert invalid_status.status_code == 422
    assert invalid_category.status_code == 422
