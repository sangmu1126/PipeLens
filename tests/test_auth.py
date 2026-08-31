import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from pipelens.config import Settings
from pipelens.main import create_app
from pipelens.models import AnalysisRecord, GitHubUser


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
        me = client.get("/api/v1/me")
        analyses = client.get("/api/v1/analyses")

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
        response = client.get("/api/v1/analyses")

    assert response.status_code == 401


def test_authentication_rotates_fallback_encryption_key(tmp_path: Path) -> None:
    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()
    app = create_app(
        _settings(tmp_path).model_copy(
            update={
                "token_encryption_key": new_key.decode(),
                "token_encryption_fallback_keys": old_key.decode(),
            }
        )
    )
    session_token = "session-token"
    session_hash = hashlib.sha256(session_token.encode()).hexdigest()
    old_encrypted_token = Fernet(old_key).encrypt(b"github-user-token").decode()
    with TestClient(app):
        app.state.store.upsert_github_user(GitHubUser(github_user_id=42, login="octocat"))
        app.state.store.create_auth_session(
            session_hash,
            42,
            old_encrypted_token,
            datetime.now(UTC) + timedelta(days=1),
        )

        session = app.state.auth.authenticate(session_token)
        stored = app.state.store.get_auth_session(session_hash)

    assert session is not None
    assert session.access_token == "github-user-token"
    assert stored is not None
    rotated_token = stored["encrypted_access_token"]
    assert rotated_token != old_encrypted_token
    assert Fernet(new_key).decrypt(rotated_token.encode()) == b"github-user-token"


def test_authentication_rejects_token_without_matching_fallback_key(tmp_path: Path) -> None:
    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()
    app = create_app(
        _settings(tmp_path).model_copy(
            update={"token_encryption_key": new_key.decode()}
        )
    )
    session_token = "session-token"
    session_hash = hashlib.sha256(session_token.encode()).hexdigest()
    with TestClient(app):
        app.state.store.upsert_github_user(GitHubUser(github_user_id=42, login="octocat"))
        app.state.store.create_auth_session(
            session_hash,
            42,
            Fernet(old_key).encrypt(b"github-user-token").decode(),
            datetime.now(UTC) + timedelta(days=1),
        )

        session = app.state.auth.authenticate(session_token)

        assert session is None
        assert app.state.store.get_auth_session(session_hash) is None
