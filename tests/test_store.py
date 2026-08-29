from pathlib import Path

import pytest

from pipelens.models import (
    AnalysisRecord,
    AnalysisStage,
    AnalysisStatus,
    Classification,
    ErrorCategory,
    ExecutionContext,
    FailedJobContext,
    FeedbackAccuracy,
    FeedbackRequest,
    RelatedFile,
    StageStatus,
    TrustLevel,
)
from pipelens.store import AnalysisAttemptSuperseded, AnalysisStore


def test_store_deduplicates_workflow_run(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "test.db"))
    store.initialize()
    record = AnalysisRecord(
        run_id=42,
        delivery_id="delivery-1",
        repository="acme/example",
        workflow_name="CI",
        head_sha="abc123",
        html_url="https://github.com/acme/example/actions/runs/42",
        installation_id=7,
    )

    assert store.create_if_absent(record) is True
    assert store.create_if_absent(record) is False
    assert store.get(42).status == AnalysisStatus.QUEUED


def test_store_lists_only_runnable_queued_analyses(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "test.db"))
    store.initialize()
    for run_id, installation_id in [(50, 7), (51, 7), (52, None)]:
        store.create_if_absent(
            AnalysisRecord(
                run_id=run_id,
                delivery_id=f"delivery-{run_id}",
                repository="acme/example",
                workflow_name="CI",
                head_sha=f"sha-{run_id}",
                html_url=f"https://github.com/acme/example/actions/runs/{run_id}",
                installation_id=installation_id,
            )
        )
    store.update(51, AnalysisStatus.COMPLETED)

    queued = store.queued_requests()

    assert [request.run_id for request in queued] == [50]
    assert queued[0].installation_id == 7


def test_store_persists_repository_correlation(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "test.db"))
    store.initialize()
    record = AnalysisRecord(
        run_id=43,
        delivery_id="delivery-2",
        repository="acme/example",
        workflow_name="CI",
        head_sha="def456",
        html_url="https://github.com/acme/example/actions/runs/43",
        installation_id=7,
    )
    store.create_if_absent(record)

    store.update(
        43,
        AnalysisStatus.COMPLETED,
        related_files=[RelatedFile(filename="src/app.py", score=0.75, reasons=["로그 직접 일치"])],
        workflow_path=".github/workflows/ci.yml",
        model_name="test-model",
        prompt_version="diagnosis-v1",
        execution_context=ExecutionContext(
            workflow_name="CI",
            head_branch="main",
            failed_jobs=[
                FailedJobContext(
                    name="tests", failed_steps=["Run pytest"], runner_labels=["ubuntu-latest"]
                )
            ],
        ),
    )

    saved = store.get(43)
    assert saved.related_files[0].filename == "src/app.py"
    assert saved.workflow_path == ".github/workflows/ci.yml"
    assert saved.model_name == "test-model"
    assert saved.prompt_version == "diagnosis-v1"
    assert saved.execution_context.failed_jobs[0].runner_labels == ["ubuntu-latest"]


def test_store_creates_and_updates_feedback(tmp_path: Path) -> None:
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
        )
    )

    created = store.save_feedback(
        44,
        FeedbackRequest(
            accuracy=FeedbackAccuracy.PARTIAL,
            suggestion_resolved=False,
            comment="원인 일부만 일치",
        ),
    )
    updated = store.save_feedback(
        44,
        FeedbackRequest(accuracy=FeedbackAccuracy.ACCURATE, suggestion_resolved=True),
    )

    assert created.created_at == updated.created_at
    assert updated.accuracy is FeedbackAccuracy.ACCURATE
    assert updated.suggestion_resolved is True
    assert store.get(44).feedback == updated


def test_store_rejects_feedback_for_unknown_analysis(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "test.db"))
    store.initialize()

    result = store.save_feedback(999, FeedbackRequest(accuracy=FeedbackAccuracy.INACCURATE))

    assert result is None


def test_store_scopes_analysis_and_feedback_to_installations(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "test.db"))
    store.initialize()
    for run_id, installation_id in [(45, 7), (46, 8)]:
        store.create_if_absent(
            AnalysisRecord(
                run_id=run_id,
                delivery_id=f"delivery-{run_id}",
                repository="acme/example",
                workflow_name="CI",
                head_sha="abc123",
                html_url=f"https://github.com/acme/example/actions/runs/{run_id}",
                installation_id=installation_id,
            )
        )

    assert [record.run_id for record in store.list(installation_ids={7})] == [45]
    assert store.get(46, installation_ids={7}) is None
    assert (
        store.save_feedback(
            46,
            FeedbackRequest(accuracy=FeedbackAccuracy.ACCURATE),
            installation_ids={7},
        )
        is None
    )


def test_store_filters_analysis_history(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "test.db"))
    store.initialize()
    records = [
        (61, "acme/api", AnalysisStatus.COMPLETED, ErrorCategory.TEST),
        (62, "acme/api", AnalysisStatus.FAILED, ErrorCategory.BUILD),
        (63, "acme/web", AnalysisStatus.COMPLETED, ErrorCategory.BUILD),
    ]
    for run_id, repository, status, category in records:
        store.create_if_absent(
            AnalysisRecord(
                run_id=run_id,
                delivery_id=f"delivery-{run_id}",
                repository=repository,
                workflow_name="CI",
                head_sha=f"sha-{run_id}",
                html_url=f"https://github.com/{repository}/actions/runs/{run_id}",
                installation_id=7,
            )
        )
        store.update(
            run_id,
            status,
            classification=Classification(
                category=category,
                confidence=0.9,
                first_error="failed",
            ),
        )

    assert [record.run_id for record in store.list(repository="acme/api")] == [62, 61]
    assert [record.run_id for record in store.list(status=AnalysisStatus.COMPLETED)] == [63, 61]
    assert [record.run_id for record in store.list(category=ErrorCategory.BUILD)] == [63, 62]
    assert [
        record.run_id
        for record in store.list(
            repository="acme/api",
            status=AnalysisStatus.COMPLETED,
            category=ErrorCategory.TEST,
        )
    ] == [61]


def test_store_persists_analysis_trust_level(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "test.db"))
    store.initialize()
    store.create_if_absent(
        AnalysisRecord(
            run_id=47,
            delivery_id="delivery-47",
            repository="acme/example",
            workflow_name="CI",
            head_sha="abc123",
            html_url="https://github.com/acme/example/actions/runs/47",
        )
    )

    store.update(
        47,
        AnalysisStatus.RUNNING,
        trust_level=TrustLevel.UNTRUSTED_FORK,
        baseline_sha="last-success-sha",
    )

    assert store.get(47).trust_level is TrustLevel.UNTRUSTED_FORK
    assert store.get(47).baseline_sha == "last-success-sha"


def test_store_records_analysis_timing_and_stage_history(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "test.db"))
    store.initialize()
    store.create_if_absent(
        AnalysisRecord(
            run_id=48,
            delivery_id="delivery-48",
            repository="acme/example",
            workflow_name="CI",
            head_sha="abc123",
            html_url="https://github.com/acme/example/actions/runs/48",
        )
    )

    start = store.begin_analysis(48)
    store.record_stage(48, AnalysisStage.COLLECTING, StageStatus.STARTED)
    store.record_stage(48, AnalysisStage.COLLECTING, StageStatus.COMPLETED)
    total_latency = store.finish_analysis(48, start.attempt_started_at)

    saved = store.get(48)
    assert saved.analysis_started_at is not None
    assert saved.analysis_completed_at is not None
    assert saved.duration_seconds is not None and saved.duration_seconds >= 0
    assert saved.queue_wait_seconds is not None and saved.queue_wait_seconds >= 0
    assert saved.total_latency_seconds == total_latency
    assert start.first_start is True
    assert [event.status for event in saved.stage_history] == [
        StageStatus.STARTED,
        StageStatus.COMPLETED,
    ]


def test_new_analysis_attempt_fences_stale_worker_updates(tmp_path: Path) -> None:
    store = AnalysisStore(str(tmp_path / "test.db"))
    store.initialize()
    store.create_if_absent(
        AnalysisRecord(
            run_id=49,
            delivery_id="delivery-49",
            repository="acme/example",
            workflow_name="CI",
            head_sha="abc123",
            html_url="https://github.com/acme/example/actions/runs/49",
            installation_id=7,
        )
    )

    first_start = store.begin_analysis(49, "attempt-a")
    store.record_stage(
        49,
        AnalysisStage.COLLECTING,
        StageStatus.STARTED,
        attempt_token="attempt-a",
    )
    second_start = store.begin_analysis(49, "attempt-b")

    with pytest.raises(AnalysisAttemptSuperseded):
        store.update(49, AnalysisStatus.RUNNING, error="stale", attempt_token="attempt-a")
    with pytest.raises(AnalysisAttemptSuperseded):
        store.finish_analysis(49, first_start.attempt_started_at, attempt_token="attempt-a")
    with pytest.raises(AnalysisAttemptSuperseded):
        store.record_stage(
            49,
            AnalysisStage.COLLECTING,
            StageStatus.COMPLETED,
            attempt_token="attempt-a",
        )

    assert store.get(49).stage_history[0].status is StageStatus.FAILED
    assert "Superseded" in store.get(49).stage_history[0].error

    store.finish_analysis(49, second_start.attempt_started_at, attempt_token="attempt-b")
    assert second_start.first_start is False
    assert second_start.queue_wait_seconds == first_start.queue_wait_seconds
    with pytest.raises(AnalysisAttemptSuperseded):
        store.begin_analysis(49, "attempt-c")
    assert store.get(49).status is AnalysisStatus.COMPLETED
