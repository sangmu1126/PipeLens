"""Deterministic GitHub boundary for the browser OAuth acceptance test."""

from pathlib import Path

import httpx
from fastapi import Query
from fastapi.responses import HTMLResponse

from pipelens.config import Settings
from pipelens.main import create_app


def _github_response(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/mock-github/login/oauth/access_token":
        return httpx.Response(200, json={"access_token": "browser-e2e-token"})
    if request.url.path == "/user":
        return httpx.Response(
            200,
            json={"id": 42, "login": "octocat", "avatar_url": None},
        )
    if request.url.path == "/user/installations":
        return httpx.Response(
            200,
            json={
                "installations": [
                    {
                        "id": 99,
                        "account": {"login": "acme", "type": "Organization"},
                        "repository_selection": "all",
                    }
                ]
            },
        )
    return httpx.Response(404)


database_path = Path("frontend/test-results/browser-e2e.db")
database_path.parent.mkdir(parents=True, exist_ok=True)

app = create_app(
    Settings(
        database_path=str(database_path),
        github_client_id="browser-e2e-client",
        github_client_secret="browser-e2e-secret",
        github_app_slug="pipelens-browser-e2e",
        public_url="http://127.0.0.1:5173",
        session_secret="browser-e2e-session-secret",
    )
)
app.state.auth.github.transport = httpx.MockTransport(_github_response)
app.state.auth.github.web_url = "http://127.0.0.1:8000/mock-github"


@app.get("/mock-github/login/oauth/authorize", response_class=HTMLResponse)
async def authorize(
    client_id: str,
    redirect_uri: str,
    state: str = Query(min_length=1),
) -> str:
    if client_id != "browser-e2e-client":
        return "invalid client"
    callback = httpx.URL(redirect_uri).copy_add_param("code", "browser-e2e-code").copy_add_param(
        "state", state
    )
    return f'<a href="{callback}">PipeLens 승인</a>'
