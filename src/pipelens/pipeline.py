import asyncio
import logging
from contextlib import suppress

from pipelens.classifier import classify_log, extract_error_context
from pipelens.config import Settings
from pipelens.diagnosis import build_rule_based_diagnosis, validate_diagnosis
from pipelens.github import GitHubClient
from pipelens.models import AnalysisRequest, AnalysisStatus
from pipelens.sanitizer import sanitize_log
from pipelens.store import AnalysisStore

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    def __init__(self, settings: Settings, store: AnalysisStore, github: GitHubClient) -> None:
        self.settings = settings
        self.store = store
        self.github = github
        self.queue: asyncio.Queue[AnalysisRequest] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._worker = asyncio.create_task(self._run(), name="pipelens-analysis-worker")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker

    async def enqueue(self, request: AnalysisRequest) -> None:
        await self.queue.put(request)

    async def _run(self) -> None:
        while True:
            request = await self.queue.get()
            try:
                await self.analyze(request)
            except Exception as exc:
                logger.exception("analysis failed for run %s", request.run_id)
                self.store.update(request.run_id, AnalysisStatus.FAILED, error=str(exc))
            finally:
                self.queue.task_done()

    async def analyze(self, request: AnalysisRequest) -> None:
        self.store.update(request.run_id, AnalysisStatus.RUNNING)
        token = await self.github.installation_token(request.installation_id)
        failed_jobs, logs = await asyncio.gather(
            self.github.failed_job_names(request.repository, request.run_id, token),
            self.github.download_logs(request.repository, request.run_id, token),
        )
        matching_logs = [log for log in logs if any(name in log.job_name for name in failed_jobs)]
        selected = matching_logs or logs
        combined = "\n".join(log.text for log in selected)
        sanitized, _redactions = sanitize_log(combined)
        context = extract_error_context(sanitized, self.settings.error_context_lines)
        classification = classify_log(context, related_step=", ".join(failed_jobs) or None)
        diagnosis = validate_diagnosis(build_rule_based_diagnosis(classification), context)
        self.store.update(
            request.run_id,
            AnalysisStatus.COMPLETED,
            classification=classification,
            diagnosis=diagnosis,
        )
        if self.settings.publish_checks:
            evidence = "\n\n".join(f"> {item.content}" for item in diagnosis.evidence)
            suggestions = "\n".join(f"- {item.description}" for item in diagnosis.suggestions)
            summary = (
                f"{diagnosis.root_cause}\n\n### 근거\n{evidence}\n\n### 권장 조치\n{suggestions}"
            )
            await self.github.create_check(
                request.repository, request.head_sha, token, diagnosis.summary, summary
            )
