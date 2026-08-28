import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import generate_latest

from pipelens.config import Settings
from pipelens.github import FailedJob, JobLog
from pipelens.models import (
    AnalysisRecord,
    AnalysisRequest,
    AnalysisStage,
    AnalysisStatus,
    RepositoryContext,
    StageStatus,
    TrustLevel,
)
from pipelens.pipeline import AnalysisPipeline
from pipelens.store import AnalysisStore


@pytest.mark.asyncio
async def test_context_failure_does_not_discard_log_diagnosis(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "test.db"))
    store.initialize()
    store.create_if_absent(
        AnalysisRecord(
            run_id=44,
            delivery_id="delivery-44",
            repository="acme/example",
            workflow_name="CI",
            head_sha="abc123",
            html_url="https://github.com/acme/example/actions/runs/44",
            installation_id=7,
        )
    )
    github = MagicMock()
    github.installation_token = AsyncMock(return_value="token")
    github.failed_jobs = AsyncMock(
        return_value=[FailedJob(job_id=1, name="tests", failed_steps=("Run pytest",))]
    )
    github.download_logs = AsyncMock(
        return_value=[JobLog(job_name="tests", text="pytest: 1 failed, 2 passed")]
    )
    github.repository_context = AsyncMock(side_effect=RuntimeError("GitHub unavailable"))
    pipeline = AnalysisPipeline(Settings(database_path=store.database_path), store, github)

    await pipeline.analyze(
        AnalysisRequest(
            run_id=44,
            repository="acme/example",
            installation_id=7,
            head_sha="abc123",
        )
    )

    result = store.get(44)
    assert result.status is AnalysisStatus.COMPLETED
    assert result.classification.category == "test_failure"
    assert result.classification.related_step == "tests / Run pytest"
    assert result.diagnosis.notes == ["로그와 직접 연결되는 변경 파일을 찾지 못했습니다."]
    assert result.duration_seconds is not None
    completed_stages = [
        event.stage
        for event in result.stage_history
        if event.status is StageStatus.COMPLETED
    ]
    assert completed_stages == [
        AnalysisStage.COLLECTING,
        AnalysisStage.SANITIZING,
        AnalysisStage.CLASSIFYING,
        AnalysisStage.CORRELATING,
        AnalysisStage.DIAGNOSING,
        AnalysisStage.PUBLISHING,
    ]
    metrics = generate_latest(pipeline.metrics.registry).decode()
    assert 'pipelens_analyses_total{status="completed"} 1.0' in metrics
    assert 'pipelens_error_categories_total{category="test_failure"} 1.0' in metrics
    assert 'pipelens_log_chunks_total{kind="processed"} 1.0' in metrics


@pytest.mark.asyncio
async def test_llm_failure_records_attempt_and_uses_rule_fallback(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "test.db"))
    store.initialize()
    store.create_if_absent(
        AnalysisRecord(
            run_id=45,
            delivery_id="delivery-45",
            repository="acme/example",
            workflow_name="CI",
            head_sha="def456",
            html_url="https://github.com/acme/example/actions/runs/45",
            installation_id=7,
        )
    )
    github = MagicMock()
    github.installation_token = AsyncMock(return_value="token")
    github.failed_jobs = AsyncMock(
        return_value=[FailedJob(job_id=1, name="tests", failed_steps=("Run pytest",))]
    )
    github.download_logs = AsyncMock(
        return_value=[JobLog(job_name="tests", text="pytest: 1 failed, 2 passed")]
    )
    github.repository_context = AsyncMock(return_value=RepositoryContext())
    provider = MagicMock(model_name="test-model")
    provider.analyze = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    pipeline = AnalysisPipeline(
        Settings(database_path=store.database_path), store, github, provider
    )

    await pipeline.analyze(
        AnalysisRequest(
            run_id=45,
            repository="acme/example",
            installation_id=7,
            head_sha="def456",
        )
    )

    result = store.get(45)
    assert result.status is AnalysisStatus.COMPLETED
    assert result.classification.category == "test_failure"
    assert "LLM 분석에 실패" in result.diagnosis.notes[0]
    assert result.model_name == "test-model"
    assert result.prompt_version == "diagnosis-v1"
    metrics = generate_latest(pipeline.metrics.registry).decode()
    assert 'pipelens_llm_requests_total{model="test-model",status="failed"} 1.0' in metrics


@pytest.mark.asyncio
@pytest.mark.parametrize(("pull_request_number", "expected_method"), [(55, "pr"), (None, "check")])
async def test_publishes_pr_comment_or_commit_check(
    tmp_path: Path, pull_request_number: int | None, expected_method: str
) -> None:
    run_id = 50 if pull_request_number else 51
    store = AnalysisStore(str(tmp_path / f"{run_id}.db"))
    store.initialize()
    store.create_if_absent(
        AnalysisRecord(
            run_id=run_id,
            delivery_id=f"delivery-{run_id}",
            repository="acme/example",
            workflow_name="CI",
            head_sha="abc123",
            html_url=f"https://github.com/acme/example/actions/runs/{run_id}",
            installation_id=7,
        )
    )
    github = MagicMock()
    github.installation_token = AsyncMock(return_value="token")
    github.failed_jobs = AsyncMock(
        return_value=[FailedJob(job_id=1, name="tests", failed_steps=("Run pytest",))]
    )
    github.download_logs = AsyncMock(
        return_value=[JobLog(job_name="tests", text="pytest: 1 failed, 2 passed")]
    )
    github.repository_context = AsyncMock(
        return_value=RepositoryContext(pull_request_number=pull_request_number)
    )
    github.upsert_pull_request_comment = AsyncMock()
    github.upsert_check = AsyncMock()
    pipeline = AnalysisPipeline(
        Settings(
            database_path=store.database_path,
            publish_checks=True,
            public_url="https://pipelens.example",
        ),
        store,
        github,
    )

    await pipeline.analyze(
        AnalysisRequest(
            run_id=run_id,
            repository="acme/example",
            installation_id=7,
            head_sha="abc123",
        )
    )

    if expected_method == "pr":
        github.upsert_pull_request_comment.assert_awaited_once()
        github.upsert_check.assert_not_awaited()
        assert github.upsert_pull_request_comment.await_args.args[1:3] == (55, run_id)
    else:
        github.upsert_check.assert_awaited_once()
        github.upsert_pull_request_comment.assert_not_awaited()
        assert github.upsert_check.await_args.args[-1] == (
            f"https://pipelens.example/?run_id={run_id}"
        )


@pytest.mark.asyncio
async def test_untrusted_fork_uses_rules_without_llm_and_skips_commit_check(
    tmp_path: Path,
) -> None:
    store = AnalysisStore(str(tmp_path / "fork.db"))
    store.initialize()
    store.create_if_absent(
        AnalysisRecord(
            run_id=52,
            delivery_id="delivery-52",
            repository="acme/example",
            workflow_name="CI",
            head_sha="abc123",
            html_url="https://github.com/acme/example/actions/runs/52",
            installation_id=7,
        )
    )
    github = MagicMock()
    github.installation_token = AsyncMock(return_value="token")
    github.failed_jobs = AsyncMock(
        return_value=[FailedJob(job_id=1, name="tests", failed_steps=("Run pytest",))]
    )
    github.download_logs = AsyncMock(
        return_value=[JobLog(job_name="tests", text="pytest: 1 failed, 2 passed")]
    )
    github.repository_context = AsyncMock(
        return_value=RepositoryContext(trust_level=TrustLevel.UNTRUSTED_FORK)
    )
    github.upsert_pull_request_comment = AsyncMock()
    github.upsert_check = AsyncMock()
    provider = MagicMock(model_name="test-model")
    provider.analyze = AsyncMock()
    pipeline = AnalysisPipeline(
        Settings(database_path=store.database_path, publish_checks=True),
        store,
        github,
        provider,
    )

    await pipeline.analyze(
        AnalysisRequest(
            run_id=52,
            repository="acme/example",
            installation_id=7,
            head_sha="abc123",
        )
    )

    result = store.get(52)
    assert result.trust_level is TrustLevel.UNTRUSTED_FORK
    assert "규칙 기반 진단만" in result.diagnosis.notes[0]
    provider.analyze.assert_not_awaited()
    github.upsert_pull_request_comment.assert_not_awaited()
    github.upsert_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_records_failed_stage_and_attempt_duration(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "failed-stage.db"))
    store.initialize()
    store.create_if_absent(
        AnalysisRecord(
            run_id=53,
            delivery_id="delivery-53",
            repository="acme/example",
            workflow_name="CI",
            head_sha="abc123",
            html_url="https://github.com/acme/example/actions/runs/53",
            installation_id=7,
        )
    )
    github = MagicMock()
    github.installation_token = AsyncMock(side_effect=RuntimeError("GitHub unavailable"))
    pipeline = AnalysisPipeline(Settings(database_path=store.database_path), store, github)

    with pytest.raises(RuntimeError, match="GitHub unavailable"):
        await pipeline.analyze(
            AnalysisRequest(
                run_id=53,
                repository="acme/example",
                installation_id=7,
                head_sha="abc123",
            )
        )

    result = store.get(53)
    assert result.status is AnalysisStatus.FAILED
    assert result.duration_seconds is not None
    assert result.stage_history[-1].stage is AnalysisStage.COLLECTING
    assert result.stage_history[-1].status is StageStatus.FAILED
    assert result.stage_history[-1].error == "GitHub unavailable"


@pytest.mark.asyncio
async def test_new_attempt_fences_resumed_stale_pipeline(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "fencing.db"))
    store.initialize()
    store.create_if_absent(
        AnalysisRecord(
            run_id=54,
            delivery_id="delivery-54",
            repository="acme/example",
            workflow_name="CI",
            head_sha="abc123",
            html_url="https://github.com/acme/example/actions/runs/54",
            installation_id=7,
        )
    )
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    token_calls = 0

    async def installation_token(_: int) -> str:
        nonlocal token_calls
        token_calls += 1
        if token_calls == 1:
            first_started.set()
            await release_first.wait()
        return "token"

    github = MagicMock()
    github.installation_token = AsyncMock(side_effect=installation_token)
    github.failed_jobs = AsyncMock(
        return_value=[FailedJob(job_id=1, name="tests", failed_steps=("Run pytest",))]
    )
    github.download_logs = AsyncMock(
        return_value=[JobLog(job_name="tests", text="pytest: 1 failed, 2 passed")]
    )
    github.repository_context = AsyncMock(return_value=RepositoryContext())
    github.upsert_check = AsyncMock()
    pipeline = AnalysisPipeline(
        Settings(
            database_path=store.database_path,
            publish_checks=True,
            public_url="https://pipelens.example",
        ),
        store,
        github,
    )
    request = AnalysisRequest(
        run_id=54,
        repository="acme/example",
        installation_id=7,
        head_sha="abc123",
    )

    stale_task = asyncio.create_task(pipeline.analyze(request))
    await first_started.wait()
    await pipeline.analyze(request)
    release_first.set()
    await stale_task

    result = store.get(54)
    assert result.status is AnalysisStatus.COMPLETED
    assert any(
        event.status is StageStatus.FAILED and "Superseded" in (event.error or "")
        for event in result.stage_history
    )
    github.upsert_check.assert_awaited_once()
    metrics = generate_latest(pipeline.metrics.registry).decode()
    assert 'pipelens_analyses_total{status="completed"} 1.0' in metrics
    assert 'pipelens_analyses_total{status="superseded"} 1.0' in metrics
