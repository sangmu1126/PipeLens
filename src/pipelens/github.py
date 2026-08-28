import io
import time
import zipfile
from dataclasses import dataclass

import httpx
import jwt


class GitHubConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobLog:
    job_name: str
    text: str


class GitHubClient:
    api_url = "https://api.github.com"

    def __init__(self, app_id: str | None, private_key: str | None, max_log_bytes: int) -> None:
        self.app_id = app_id
        self.private_key = private_key.replace("\\n", "\n") if private_key else None
        self.max_log_bytes = max_log_bytes

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
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.api_url}/app/installations/{installation_id}/access_tokens", headers=headers
            )
            response.raise_for_status()
            return response.json()["token"]

    async def failed_job_names(self, repository: str, run_id: int, token: str) -> list[str]:
        async with httpx.AsyncClient(timeout=30) as client:
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
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
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
        async with httpx.AsyncClient(timeout=30) as client:
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
