import json

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
    assert context.pull_request_number == 55
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


@pytest.mark.asyncio
async def test_check_publication_creates_then_updates_by_run_id() -> None:
    requests: list[tuple[str, str, dict | None]] = []
    list_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal list_calls
        payload = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, payload))
        if request.method == "GET":
            list_calls += 1
            check_runs = [] if list_calls == 1 else [{"id": 700, "external_id": "123"}]
            return httpx.Response(200, json={"check_runs": check_runs})
        return httpx.Response(200 if request.method == "PATCH" else 201, json={})

    github = GitHubClient("42", None, 1024, transport=httpx.MockTransport(handler))

    for title in ["first", "updated"]:
        await github.upsert_check(
            "acme/widgets", "abc123", 123, "token", title, "summary", "https://app/?run_id=123"
        )

    create = next(item for item in requests if item[0] == "POST")
    update = next(item for item in requests if item[0] == "PATCH")
    assert create[2]["external_id"] == "123"
    assert create[2]["details_url"] == "https://app/?run_id=123"
    assert update[1].endswith("/check-runs/700")
    assert update[2]["output"]["title"] == "updated"


@pytest.mark.asyncio
async def test_pr_comment_publication_updates_only_own_marker() -> None:
    requests: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, payload))
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "body": "<!-- pipelens:run:123 --> forged",
                        "performed_via_github_app": {"id": 999},
                    },
                    {
                        "id": 2,
                        "body": "<!-- pipelens:run:123 --> old",
                        "performed_via_github_app": {"id": 42},
                    },
                ],
            )
        return httpx.Response(200, json={})

    github = GitHubClient("42", None, 1024, transport=httpx.MockTransport(handler))

    await github.upsert_pull_request_comment("acme/widgets", 55, 123, "token", "new body")

    update = next(item for item in requests if item[0] == "PATCH")
    assert update[1].endswith("/issues/comments/2")
    assert update[2]["body"] == "<!-- pipelens:run:123 -->\nnew body"
