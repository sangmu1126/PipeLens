from datetime import UTC, datetime
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
            "/api/v1/analyses",
            params={
                "repository": "acme/api",
                "status": "completed",
                "category": "test_failure",
            },
        )
        invalid_status = client.get("/api/v1/analyses", params={"status": "unknown"})
        invalid_category = client.get("/api/v1/analyses", params={"category": "network"})

    assert filtered.status_code == 200
    assert [record["run_id"] for record in filtered.json()] == [701]
    assert invalid_status.status_code == 422
    assert invalid_category.status_code == 422


def test_analysis_list_uses_stable_cursor_pagination(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=str(tmp_path / "db.sqlite"), auth_required=False))
    created_at = datetime(2026, 8, 29, 12, tzinfo=UTC)

    with TestClient(app) as client:
        for run_id in [801, 802, 803]:
            app.state.store.create_if_absent(
                AnalysisRecord(
                    run_id=run_id,
                    delivery_id=f"delivery-{run_id}",
                    repository="acme/api",
                    workflow_name="CI",
                    head_sha=f"sha-{run_id}",
                    html_url=f"https://github.com/acme/api/actions/runs/{run_id}",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )

        first = client.get("/api/v1/analyses", params={"limit": 2})
        cursor = first.headers["X-PipeLens-Next-Cursor"]
        second = client.get("/api/v1/analyses", params={"limit": 2, "cursor": cursor})
        invalid = client.get("/api/v1/analyses", params={"cursor": "not-a-cursor"})

    assert [record["run_id"] for record in first.json()] == [803, 802]
    assert [record["run_id"] for record in second.json()] == [801]
    assert "X-PipeLens-Next-Cursor" not in second.headers
    assert invalid.status_code == 422
