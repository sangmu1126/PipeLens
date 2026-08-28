import json

import httpx
import pytest

from pipelens.github import GitHubClient
from pipelens.models import TrustLevel


@pytest.mark.asyncio
async def test_repository_context_uses_pr_files_and_workflow_at_head_sha() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        path = request.url.path
        if path.endswith("/actions/runs/123"):
            return httpx.Response(
                200,
                json={
                    "workflow_id": 7,
                    "pull_requests": [
                        {
                            "number": 55,
                            "head": {"repo": {"id": 2, "full_name": "contributor/widgets"}},
                            "base": {"repo": {"id": 1, "full_name": "acme/widgets"}},
                        }
                    ],
                },
            )
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
    assert context.trust_level is TrustLevel.UNTRUSTED_FORK
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
async def test_failed_jobs_include_failed_step_names() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 10,
                        "name": "tests (3.12)",
                        "conclusion": "failure",
                        "labels": ["ubuntu-latest", "x64"],
                        "workflow_name": "CI",
                        "head_branch": "feature/fix",
                        "steps": [
                            {"name": "Checkout", "conclusion": "success"},
                            {"name": "Run pytest", "conclusion": "failure"},
                            {"name": "Cleanup", "conclusion": "skipped"},
                        ],
                    },
                    {"id": 11, "name": "lint", "conclusion": "success", "steps": []},
                ]
            },
        )

    github = GitHubClient(None, None, 1024, transport=httpx.MockTransport(handler))

    jobs = await github.failed_jobs("acme/widgets", 123, "token")

    assert len(jobs) == 1
    assert jobs[0].job_id == 10
    assert jobs[0].name == "tests (3.12)"
    assert jobs[0].failed_steps == ("Run pytest",)
    assert jobs[0].runner_labels == ("ubuntu-latest", "x64")
    assert jobs[0].workflow_name == "CI"
    assert jobs[0].head_branch == "feature/fix"


@pytest.mark.asyncio
async def test_failed_jobs_retries_github_rate_limit() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(403, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"jobs": []})

    github = GitHubClient(None, None, 1024, transport=httpx.MockTransport(handler))

    assert await github.failed_jobs("acme/widgets", 123, "token") == []
    assert calls == 2


@pytest.mark.asyncio
async def test_repository_context_compares_from_previous_successful_run() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        path = request.url.path
        if path.endswith("/actions/runs/200"):
            return httpx.Response(
                200,
                json={
                    "workflow_id": 7,
                    "head_branch": "main",
                    "created_at": "2026-08-29T10:00:00Z",
                    "pull_requests": [],
                },
            )
        if path.endswith("/actions/workflows/7/runs"):
            return httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "head_sha": "lastgood",
                            "created_at": "2026-08-29T09:00:00Z",
                        }
                    ]
                },
            )
        if "/compare/lastgood...failedsha" in path:
            return httpx.Response(
                200,
                json={
                    "files": [
                        {
                            "filename": "src/regression.py",
                            "status": "modified",
                            "patch": "+broken = True",
                        }
                    ]
                },
            )
        if path.endswith("/actions/workflows/7"):
            return httpx.Response(200, json={"path": ".github/workflows/ci.yml"})
        if path.endswith("/contents/.github/workflows/ci.yml"):
            return httpx.Response(200, text="name: CI")
        return httpx.Response(404)

    github = GitHubClient(None, None, 1024, transport=httpx.MockTransport(handler))

    context = await github.repository_context("acme/widgets", 200, "failedsha", "token")

    assert context.baseline_sha == "lastgood"
    assert context.changed_files[0].filename == "src/regression.py"
    assert any("branch=main" in url and "status=success" in url for url in requested)
    assert any("/compare/lastgood...failedsha" in url for url in requested)


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
