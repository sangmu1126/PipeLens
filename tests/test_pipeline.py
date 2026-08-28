from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import generate_latest

from pipelens.config import Settings
from pipelens.github import JobLog
from pipelens.models import AnalysisRecord, AnalysisRequest, AnalysisStatus, RepositoryContext
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
    github.failed_job_names = AsyncMock(return_value=["tests"])
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
    assert result.diagnosis.notes == ["로그와 직접 연결되는 변경 파일을 찾지 못했습니다."]
    metrics = generate_latest(pipeline.metrics.registry).decode()
    assert 'pipelens_analyses_total{status="completed"} 1.0' in metrics
    assert 'pipelens_error_categories_total{category="test_failure"} 1.0' in metrics


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
    github.failed_job_names = AsyncMock(return_value=["tests"])
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
