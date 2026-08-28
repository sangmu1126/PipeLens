from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from pipelens.config import Settings
from pipelens.main import create_app
from pipelens.models import AnalysisRecord


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=str(tmp_path / "auth.db"),
        github_client_id="client-id",
        github_client_secret="client-secret",
        github_app_slug="pipelens-test",
        session_secret="test-session-secret",
        public_url="http://testserver",
    )


def test_oauth_login_creates_session_and_syncs_verified_installations(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "github-user-token"})
        if request.url.path == "/user":
            return httpx.Response(
                200,
                json={"id": 42, "login": "octocat", "avatar_url": "https://img/42"},
            )
        if request.url.path == "/user/installations":
            return httpx.Response(
                200,
                json={
                    "installations": [
                        {
                            "id": 99,
                            "account": {"login": "acme", "type": "Organization"},
                            "repository_selection": "selected",
                        }
                    ]
                },
            )
        return httpx.Response(404)

    app.state.auth.github.transport = httpx.MockTransport(handler)
    with TestClient(app) as client:
        for run_id, installation_id in [(100, 99), (200, 12345)]:
            app.state.store.create_if_absent(
                AnalysisRecord(
                    run_id=run_id,
                    delivery_id=f"delivery-{run_id}",
                    repository="acme/widgets",
                    workflow_name="CI",
                    head_sha="abc123",
                    html_url=f"https://github.com/acme/widgets/actions/runs/{run_id}",
                    installation_id=installation_id,
                )
            )
        login = client.get("/auth/github/login", follow_redirects=False)
        query = parse_qs(urlparse(login.headers["location"]).query)
        callback = client.get(
            "/auth/github/callback",
            params={"code": "oauth-code", "state": query["state"][0]},
            follow_redirects=False,
        )
        me = client.get("/api/me")
        analyses = client.get("/api/analyses")

    assert callback.status_code == 303
    assert "pipelens_session=" in callback.headers["set-cookie"]
    assert me.json()["login"] == "octocat"
    assert me.json()["installations"][0]["installation_id"] == 99
    assert [item["run_id"] for item in analyses.json()] == [100]


def test_setup_rejects_spoofed_installation_id(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "token"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 1, "login": "user"})
        if request.url.path == "/user/installations":
            return httpx.Response(200, json={"installations": []})
        return httpx.Response(404)

    app.state.auth.github.transport = httpx.MockTransport(handler)
    with TestClient(app) as client:
        login = client.get("/auth/github/login", follow_redirects=False)
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        client.get(
            "/auth/github/callback",
            params={"code": "code", "state": state},
            follow_redirects=False,
        )
        setup = client.get("/github/setup?installation_id=999", follow_redirects=False)

    assert setup.status_code == 403


def test_oauth_callback_rejects_invalid_state(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))

    with TestClient(app) as client:
        client.get("/auth/github/login", follow_redirects=False)
        response = client.get(
            "/auth/github/callback?code=code&state=attacker-state", follow_redirects=False
        )

    assert response.status_code == 400


def test_analysis_api_requires_login_by_default(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))

    with TestClient(app) as client:
        response = client.get("/api/analyses")

    assert response.status_code == 401
