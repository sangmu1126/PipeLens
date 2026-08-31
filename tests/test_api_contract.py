from pathlib import Path

from fastapi.testclient import TestClient

from pipelens.config import Settings
from pipelens.main import DEPRECATION_POLICY_URL, LEGACY_API_DEPRECATION, create_app


def test_openapi_marks_only_legacy_api_operations_deprecated(tmp_path: Path) -> None:
    app = create_app(
        Settings(database_path=str(tmp_path / "contract.db"), auth_required=False)
    )
    schema = app.openapi()

    for path in (
        "/api/v1/me",
        "/api/v1/analyses",
        "/api/v1/analyses/{run_id}",
        "/api/v1/analyses/{run_id}/feedback",
    ):
        assert path in schema["paths"]
        assert not any(
            operation.get("deprecated", False)
            for operation in schema["paths"][path].values()
        )

    for path in (
        "/api/me",
        "/api/analyses",
        "/api/analyses/{run_id}",
        "/api/analyses/{run_id}/feedback",
    ):
        assert path in schema["paths"]
        assert all(
            operation["deprecated"] for operation in schema["paths"][path].values()
        )


def test_legacy_api_returns_runtime_deprecation_headers(tmp_path: Path) -> None:
    app = create_app(
        Settings(database_path=str(tmp_path / "legacy.db"), auth_required=False)
    )

    with TestClient(app) as client:
        legacy = client.get("/api/analyses")
        current = client.get("/api/v1/analyses")

    assert legacy.status_code == 200
    assert legacy.headers["Deprecation"] == LEGACY_API_DEPRECATION
    assert legacy.headers["Link"] == (
        f'<{DEPRECATION_POLICY_URL}>; rel="deprecation"; type="text/html"'
    )
    assert "Deprecation" not in current.headers
    assert legacy.json() == current.json()
