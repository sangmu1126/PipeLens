import httpx
import pytest

from pipelens.github import GitHubClient


@pytest.mark.asyncio
async def test_repository_context_uses_pr_files_and_workflow_at_head_sha() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        path = request.url.path
        if path.endswith("/actions/runs/123"):
            return httpx.Response(200, json={"workflow_id": 7, "pull_requests": [{"number": 55}]})
        if path.endswith("/pulls/55/files"):
            return httpx.Response(
                200,
                json=[
                    {
                        "filename": "src/app.py",
                        "status": "modified",
                        "patch": "@@ -1 +1 @@\n-old\n+new",
                    }
                ],
            )
        if path.endswith("/actions/workflows/7"):
            return httpx.Response(200, json={"path": ".github/workflows/ci.yml"})
        if path.endswith("/contents/.github/workflows/ci.yml"):
            return httpx.Response(200, text="name: CI")
        return httpx.Response(404)

    github = GitHubClient(None, None, 1024, transport=httpx.MockTransport(handler))

    context = await github.repository_context("acme/widgets", 123, "abc123", "token")

    assert context.changed_files[0].filename == "src/app.py"
    assert context.workflow_path == ".github/workflows/ci.yml"
    assert context.workflow_content == "name: CI"
    assert any("ref=abc123" in url for url in requested)


@pytest.mark.asyncio
async def test_github_user_oauth_and_installation_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            assert "client_secret=secret" in request.content.decode()
            return httpx.Response(200, json={"access_token": "user-token"})
        if request.url.path == "/user" and "installations" not in request.url.path:
            return httpx.Response(200, json={"id": 7, "login": "octocat"})
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

    github = GitHubClient(None, None, 1024, transport=httpx.MockTransport(handler))

    token = await github.exchange_user_code("client", "secret", "code", "https://app/callback")
    user = await github.authenticated_user(token["access_token"])
    installations = await github.user_installations(token["access_token"])

    assert user["login"] == "octocat"
    assert installations[0]["id"] == 99
