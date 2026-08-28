import io
import time
import zipfile
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from pipelens.models import ChangedFile, RepositoryContext


class GitHubConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobLog:
    job_name: str
    text: str


class GitHubClient:
    api_url = "https://api.github.com"
    web_url = "https://github.com"

    def __init__(
        self,
        app_id: str | None,
        private_key: str | None,
        max_log_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.app_id = app_id
        self.private_key = private_key.replace("\\n", "\n") if private_key else None
        self.max_log_bytes = max_log_bytes
        self.transport = transport

    @classmethod
    def authorization_url(cls, client_id: str, redirect_uri: str, state: str) -> str:
        query = urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "state": state})
        return f"{cls.web_url}/login/oauth/authorize?{query}"

    async def exchange_user_code(
        self,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
    ) -> dict:
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.post(
                f"{self.web_url}/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
            response.raise_for_status()
        payload = response.json()
        if "access_token" not in payload:
            raise GitHubConfigurationError(
                f"GitHub OAuth exchange failed: {payload.get('error', 'missing access token')}"
            )
        return payload

    async def authenticated_user(self, token: str) -> dict:
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.get(f"{self.api_url}/user", headers=self._headers(token))
            response.raise_for_status()
        return response.json()

    async def user_installations(self, token: str) -> list[dict]:
        installations: list[dict] = []
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            page = 1
            while True:
                response = await client.get(
                    f"{self.api_url}/user/installations",
                    headers=self._headers(token),
                    params={"per_page": 100, "page": page},
                )
                response.raise_for_status()
                batch = response.json().get("installations", [])
                installations.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
        return installations

    def _app_jwt(self) -> str:
        if not self.app_id or not self.private_key:
            raise GitHubConfigurationError("GitHub App credentials are not configured")
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.app_id},
            self.private_key,
            algorithm="RS256",
        )

    async def installation_token(self, installation_id: int) -> str:
        headers = self._headers(self._app_jwt())
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.post(
                f"{self.api_url}/app/installations/{installation_id}/access_tokens", headers=headers
            )
            response.raise_for_status()
            return response.json()["token"]

    async def failed_job_names(self, repository: str, run_id: int, token: str) -> list[str]:
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.get(
                f"{self.api_url}/repos/{repository}/actions/runs/{run_id}/jobs",
                headers=self._headers(token),
                params={"filter": "latest", "per_page": 100},
            )
            response.raise_for_status()
        return [
            job["name"]
            for job in response.json().get("jobs", [])
            if job.get("conclusion") == "failure"
        ]

    async def download_logs(self, repository: str, run_id: int, token: str) -> list[JobLog]:
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=True, transport=self.transport
        ) as client:
            response = await client.get(
                f"{self.api_url}/repos/{repository}/actions/runs/{run_id}/logs",
                headers=self._headers(token),
            )
            response.raise_for_status()
        if len(response.content) > self.max_log_bytes:
            raise ValueError(f"log archive exceeds {self.max_log_bytes} byte safety limit")

        logs: list[JobLog] = []
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for member in archive.infolist():
                if member.is_dir() or member.file_size > self.max_log_bytes:
                    continue
                text = archive.read(member).decode("utf-8", errors="replace")
                logs.append(JobLog(job_name=member.filename.removesuffix(".txt"), text=text))
        return logs

    async def repository_context(
        self, repository: str, run_id: int, head_sha: str, token: str
    ) -> RepositoryContext:
        headers = self._headers(token)
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            run_response = await client.get(
                f"{self.api_url}/repos/{repository}/actions/runs/{run_id}", headers=headers
            )
            run_response.raise_for_status()
            run = run_response.json()

            changed_files = await self._changed_files(
                client, repository, head_sha, headers, run.get("pull_requests", [])
            )
            workflow_path, workflow_content = await self._workflow_context(
                client, repository, run.get("workflow_id"), head_sha, headers
            )
        return RepositoryContext(
            changed_files=changed_files,
            workflow_path=workflow_path,
            workflow_content=workflow_content,
        )

    async def _changed_files(
        self,
        client: httpx.AsyncClient,
        repository: str,
        head_sha: str,
        headers: dict[str, str],
        pull_requests: list[dict],
    ) -> list[ChangedFile]:
        if pull_requests:
            number = pull_requests[0]["number"]
            response = await client.get(
                f"{self.api_url}/repos/{repository}/pulls/{number}/files",
                headers=headers,
                params={"per_page": 100},
            )
            response.raise_for_status()
            files = response.json()
        else:
            response = await client.get(
                f"{self.api_url}/repos/{repository}/commits/{head_sha}", headers=headers
            )
            response.raise_for_status()
            files = response.json().get("files", [])
        return [
            ChangedFile(
                filename=item["filename"],
                status=item.get("status", "modified"),
                patch=item.get("patch"),
                previous_filename=item.get("previous_filename"),
            )
            for item in files
        ]

    async def _workflow_context(
        self,
        client: httpx.AsyncClient,
        repository: str,
        workflow_id: int | None,
        head_sha: str,
        headers: dict[str, str],
    ) -> tuple[str | None, str | None]:
        if workflow_id is None:
            return None, None
        response = await client.get(
            f"{self.api_url}/repos/{repository}/actions/workflows/{workflow_id}", headers=headers
        )
        response.raise_for_status()
        workflow_path = response.json().get("path")
        if not workflow_path:
            return None, None
        content_response = await client.get(
            f"{self.api_url}/repos/{repository}/contents/{workflow_path}",
            headers={**headers, "Accept": "application/vnd.github.raw+json"},
            params={"ref": head_sha},
        )
        if content_response.status_code == 404:
            return workflow_path, None
        content_response.raise_for_status()
        return workflow_path, content_response.text

    async def create_check(
        self, repository: str, head_sha: str, token: str, title: str, summary: str
    ) -> None:
        body = {
            "name": "PipeLens diagnosis",
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": "neutral",
            "output": {"title": title[:255], "summary": summary[:65535]},
        }
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.post(
                f"{self.api_url}/repos/{repository}/check-runs",
                headers=self._headers(token),
                json=body,
            )
            response.raise_for_status()

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
