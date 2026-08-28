import asyncio
import logging
import uuid
from contextlib import contextmanager
from time import perf_counter

from pipelens.classifier import classify_log
from pipelens.config import Settings
from pipelens.diagnosis import build_rule_based_diagnosis, validate_diagnosis
from pipelens.github import GitHubClient
from pipelens.llm import PROMPT_VERSION, LLMContext, LLMProvider, validate_llm_analysis
from pipelens.metrics import Metrics
from pipelens.models import (
    AnalysisRequest,
    AnalysisStage,
    AnalysisStatus,
    ExecutionContext,
    FailedJobContext,
    RepositoryContext,
    StageStatus,
    TrustLevel,
)
from pipelens.preprocessing import preprocess_logs
from pipelens.publication import render_github_diagnosis
from pipelens.relevance import correlate_changed_files
from pipelens.sanitizer import sanitize_log
from pipelens.store import AnalysisAttemptSuperseded, AnalysisStore

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

    async def analyze(self, request: AnalysisRequest) -> None:
        started = perf_counter()
        attempt_token = uuid.uuid4().hex
        try:
            started_at = self.store.begin_analysis(request.run_id, attempt_token)
            await self._analyze(request, attempt_token)
        except AnalysisAttemptSuperseded:
            self.metrics.analyses.labels(status="superseded").inc()
            self.metrics.analysis_duration.observe(perf_counter() - started)
            return
        except Exception:
            try:
                self.store.finish_analysis(
                    request.run_id,
                    started_at,
                    AnalysisStatus.FAILED,
                    attempt_token,
                )
            except AnalysisAttemptSuperseded:
                self.metrics.analyses.labels(status="superseded").inc()
                self.metrics.analysis_duration.observe(perf_counter() - started)
                return
            self.metrics.analyses.labels(status="failed_attempt").inc()
            self.metrics.analysis_duration.observe(perf_counter() - started)
            raise
        try:
            self.store.finish_analysis(request.run_id, started_at, attempt_token=attempt_token)
        except AnalysisAttemptSuperseded:
            self.metrics.analyses.labels(status="superseded").inc()
            self.metrics.analysis_duration.observe(perf_counter() - started)
            return
        self.metrics.analyses.labels(status="completed").inc()
        self.metrics.analysis_duration.observe(perf_counter() - started)

    async def _analyze(self, request: AnalysisRequest, attempt_token: str) -> None:
        with self._stage(request.run_id, AnalysisStage.COLLECTING, attempt_token):
            access_token = await self.github.installation_token(request.installation_id)
            failed_jobs, logs, repository_context = await asyncio.gather(
                self.github.failed_jobs(request.repository, request.run_id, access_token),
                self.github.download_logs(request.repository, request.run_id, access_token),
                self._repository_context(
                    request.repository, request.run_id, request.head_sha, access_token
                ),
            )
            self.store.update(
                request.run_id,
                AnalysisStatus.RUNNING,
                trust_level=repository_context.trust_level,
                attempt_token=attempt_token,
            )
            self.metrics.analysis_trust.labels(level=repository_context.trust_level.value).inc()

        with self._stage(request.run_id, AnalysisStage.SANITIZING, attempt_token):
            failed_job_names = [job.name for job in failed_jobs]
            matching_logs = [
                log for log in logs if any(name in log.job_name for name in failed_job_names)
            ]
            selected = matching_logs or logs
            execution_context = self._sanitize_execution_context(failed_jobs)
            processed = preprocess_logs(
                (log.text for log in selected),
                chunk_chars=self.settings.log_chunk_chars,
                context_lines=self.settings.error_context_lines,
                max_error_chunks=self.settings.max_error_chunks,
            )
            self.metrics.record_redactions(processed.redactions)
            self.metrics.log_chunks.labels(kind="processed").inc(processed.chunks_processed)
            self.metrics.log_chunks.labels(kind="error").inc(processed.error_chunks)
            context = processed.context
            sanitized_changed_files = []
            for changed in repository_context.changed_files:
                patch, patch_redactions = sanitize_log(changed.patch or "")
                self.metrics.record_redactions(patch_redactions)
                sanitized_changed_files.append(
                    changed.model_copy(update={"patch": patch or None})
                )
            workflow_content, workflow_redactions = sanitize_log(
                repository_context.workflow_content or ""
            )
            self.metrics.record_redactions(workflow_redactions)

        with self._stage(request.run_id, AnalysisStage.CLASSIFYING, attempt_token):
            failed_locations = [
                f"{job.name} / {step}"
                for job in execution_context.failed_jobs
                for step in job.failed_steps
            ] or [job.name for job in execution_context.failed_jobs]
            classification = classify_log(
                context, related_step=", ".join(failed_locations) or None
            )
            self.metrics.error_categories.labels(category=classification.category.value).inc()

        with self._stage(request.run_id, AnalysisStage.CORRELATING, attempt_token):
            related_files = correlate_changed_files(
                context, sanitized_changed_files, classification.category
            )
            repository_files = {item.filename for item in repository_context.changed_files}
            if repository_context.workflow_path:
                repository_files.add(repository_context.workflow_path)

        with self._stage(request.run_id, AnalysisStage.DIAGNOSING, attempt_token):
            fallback_diagnosis = validate_diagnosis(
                build_rule_based_diagnosis(classification), context, repository_files
            )
            diagnosis = fallback_diagnosis
            model_name: str | None = None
            prompt_version: str | None = None
            is_untrusted_fork = repository_context.trust_level is TrustLevel.UNTRUSTED_FORK
            if is_untrusted_fork:
                diagnosis.notes.append(
                    "외부 Fork 실행이므로 신뢰할 수 없는 로그·코드·Workflow를 LLM에 "
                    "전송하지 않고 규칙 기반 진단만 수행했습니다."
                )
            if self.llm_provider and not is_untrusted_fork:
                model_name = self.llm_provider.model_name
                prompt_version = PROMPT_VERSION
                llm_context = LLMContext(
                    classification=classification,
                    log=context,
                    related_files=related_files,
                    execution_context=execution_context,
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
            AnalysisStatus.RUNNING,
            classification=classification,
            diagnosis=diagnosis,
            related_files=related_files,
            workflow_path=repository_context.workflow_path,
            model_name=model_name,
            prompt_version=prompt_version,
            trust_level=repository_context.trust_level,
            baseline_sha=repository_context.baseline_sha,
            execution_context=execution_context,
            attempt_token=attempt_token,
        )
        with self._stage(request.run_id, AnalysisStage.PUBLISHING, attempt_token):
            if self.settings.publish_checks:
                details_url = (
                    f"{self.settings.public_url.rstrip('/')}/?run_id={request.run_id}"
                )
                body = render_github_diagnosis(
                    request.run_id,
                    classification,
                    diagnosis,
                    related_files,
                    details_url,
                    repository_context.trust_level,
                    repository_context.baseline_sha,
                    request.head_sha,
                )
                if repository_context.pull_request_number is not None:
                    await self.github.upsert_pull_request_comment(
                        request.repository,
                        repository_context.pull_request_number,
                        request.run_id,
                        access_token,
                        body,
                    )
                elif not is_untrusted_fork:
                    await self.github.upsert_check(
                        request.repository,
                        request.head_sha,
                        request.run_id,
                        access_token,
                        diagnosis.summary,
                        body,
                        details_url,
                    )

    @contextmanager
    def _stage(self, run_id: int, stage: AnalysisStage, attempt_token: str):
        self.store.record_stage(
            run_id, stage, StageStatus.STARTED, attempt_token=attempt_token
        )
        try:
            yield
        except Exception as exc:
            self.store.record_stage(
                run_id,
                stage,
                StageStatus.FAILED,
                str(exc)[:2_000],
                attempt_token,
            )
            raise
        else:
            self.store.record_stage(
                run_id, stage, StageStatus.COMPLETED, attempt_token=attempt_token
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

    def _sanitize_execution_context(self, failed_jobs) -> ExecutionContext:
        def clean(value: str | None) -> str | None:
            if value is None:
                return None
            sanitized, redactions = sanitize_log(value)
            self.metrics.record_redactions(redactions)
            return sanitized

        return ExecutionContext(
            workflow_name=next(
                (clean(job.workflow_name) for job in failed_jobs if job.workflow_name), None
            ),
            head_branch=next(
                (clean(job.head_branch) for job in failed_jobs if job.head_branch), None
            ),
            failed_jobs=[
                FailedJobContext(
                    name=clean(job.name) or "unknown job",
                    failed_steps=[clean(step) or "unknown step" for step in job.failed_steps],
                    runner_labels=[
                        clean(label) or "unknown" for label in job.runner_labels
                    ],
                )
                for job in failed_jobs
            ],
        )
