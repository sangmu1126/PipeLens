from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pipelens.config import Settings
from pipelens.github import JobLog
from pipelens.models import AnalysisRecord, AnalysisRequest, AnalysisStatus
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
