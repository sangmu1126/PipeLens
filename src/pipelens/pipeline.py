import asyncio
import logging
from contextlib import suppress
from time import perf_counter

from pipelens.classifier import classify_log, extract_error_context
from pipelens.config import Settings
from pipelens.diagnosis import build_rule_based_diagnosis, validate_diagnosis
from pipelens.github import GitHubClient
from pipelens.llm import PROMPT_VERSION, LLMContext, LLMProvider, validate_llm_analysis
from pipelens.metrics import Metrics
from pipelens.models import AnalysisRequest, AnalysisStatus, RepositoryContext
from pipelens.relevance import correlate_changed_files
from pipelens.sanitizer import sanitize_log
from pipelens.store import AnalysisStore

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    def __init__(
        self,
        settings: Settings,
        store: AnalysisStore,
        github: GitHubClient,
        llm_provider: LLMProvider | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.github = github
        self.llm_provider = llm_provider
        self.metrics = metrics or Metrics()
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
        self.metrics.queue_depth.set(self.queue.qsize())

    async def _run(self) -> None:
        while True:
            request = await self.queue.get()
            self.metrics.queue_depth.set(self.queue.qsize())
            try:
                await self.analyze(request)
            except Exception as exc:
                logger.exception("analysis failed for run %s", request.run_id)
                self.store.update(request.run_id, AnalysisStatus.FAILED, error=str(exc))
            finally:
                self.queue.task_done()

    async def analyze(self, request: AnalysisRequest) -> None:
        started = perf_counter()
        try:
            await self._analyze(request)
        except Exception:
            self.metrics.analyses.labels(status="failed").inc()
            self.metrics.analysis_duration.observe(perf_counter() - started)
            raise
        self.metrics.analyses.labels(status="completed").inc()
        self.metrics.analysis_duration.observe(perf_counter() - started)

    async def _analyze(self, request: AnalysisRequest) -> None:
        self.store.update(request.run_id, AnalysisStatus.RUNNING)
        token = await self.github.installation_token(request.installation_id)
        failed_jobs, logs, repository_context = await asyncio.gather(
            self.github.failed_job_names(request.repository, request.run_id, token),
            self.github.download_logs(request.repository, request.run_id, token),
            self._repository_context(request.repository, request.run_id, request.head_sha, token),
        )
        matching_logs = [log for log in logs if any(name in log.job_name for name in failed_jobs)]
        selected = matching_logs or logs
        combined = "\n".join(log.text for log in selected)
        sanitized, redactions = sanitize_log(combined)
        self.metrics.record_redactions(redactions)
        context = extract_error_context(sanitized, self.settings.error_context_lines)
        classification = classify_log(context, related_step=", ".join(failed_jobs) or None)
        self.metrics.error_categories.labels(category=classification.category.value).inc()
        sanitized_changed_files = []
        for changed in repository_context.changed_files:
            patch, patch_redactions = sanitize_log(changed.patch or "")
            self.metrics.record_redactions(patch_redactions)
            sanitized_changed_files.append(changed.model_copy(update={"patch": patch or None}))
        related_files = correlate_changed_files(
            context, sanitized_changed_files, classification.category
        )
        repository_files = {item.filename for item in repository_context.changed_files}
        if repository_context.workflow_path:
            repository_files.add(repository_context.workflow_path)
        fallback_diagnosis = validate_diagnosis(
            build_rule_based_diagnosis(classification), context, repository_files
        )
        diagnosis = fallback_diagnosis
        model_name: str | None = None
        prompt_version: str | None = None
        if self.llm_provider:
            model_name = self.llm_provider.model_name
            prompt_version = PROMPT_VERSION
            workflow_content, workflow_redactions = sanitize_log(
                repository_context.workflow_content or ""
            )
            self.metrics.record_redactions(workflow_redactions)
            llm_context = LLMContext(
                classification=classification,
                log=context,
                related_files=related_files,
                workflow_path=repository_context.workflow_path,
                workflow_content=workflow_content or None,
            )
            llm_started = perf_counter()
            try:
                llm_result = await self.llm_provider.analyze(llm_context)
                diagnosis = validate_llm_analysis(llm_result.analysis, llm_context)
                estimated_cost = (
                    llm_result.input_tokens * self.settings.llm_input_cost_per_million
                    + llm_result.output_tokens * self.settings.llm_output_cost_per_million
                ) / 1_000_000
                self.metrics.record_llm(
                    model_name,
                    "success",
                    perf_counter() - llm_started,
                    llm_result.input_tokens,
                    llm_result.output_tokens,
                    estimated_cost,
                )
            except Exception:
                self.metrics.record_llm(model_name, "failed", perf_counter() - llm_started)
                logger.warning(
                    "LLM diagnosis failed for run %s; using rule-based result",
                    request.run_id,
                    exc_info=True,
                )
                fallback_diagnosis.notes.append(
                    "LLM 분석에 실패하여 규칙 기반 진단 결과를 제공했습니다."
                )
        if not related_files:
            diagnosis.notes.append("로그와 직접 연결되는 변경 파일을 찾지 못했습니다.")
        self.store.update(
            request.run_id,
            AnalysisStatus.COMPLETED,
            classification=classification,
            diagnosis=diagnosis,
            related_files=related_files,
            workflow_path=repository_context.workflow_path,
            model_name=model_name,
            prompt_version=prompt_version,
        )
        if self.settings.publish_checks:
            evidence = "\n\n".join(f"> {item.content}" for item in diagnosis.evidence)
            suggestions = "\n".join(f"- {item.description}" for item in diagnosis.suggestions)
            summary = (
                f"{diagnosis.root_cause}\n\n### 근거\n{evidence}\n\n### 권장 조치\n{suggestions}"
            )
            if related_files:
                files = "\n".join(
                    f"- `{item.filename}` ({item.score:.0%}): {', '.join(item.reasons)}"
                    for item in related_files
                )
                summary += f"\n\n### 관련 변경 파일\n{files}"
            else:
                summary += (
                    "\n\n### 관련 변경 파일\n로그와 직접 연결되는 변경 파일을 찾지 못했습니다."
                )
            await self.github.create_check(
                request.repository, request.head_sha, token, diagnosis.summary, summary
            )

    async def _repository_context(
        self, repository: str, run_id: int, head_sha: str, token: str
    ) -> RepositoryContext:
        try:
            return await self.github.repository_context(repository, run_id, head_sha, token)
        except Exception:
            logger.warning(
                "repository context collection failed for run %s; continuing with logs",
                run_id,
                exc_info=True,
            )
            return RepositoryContext()
