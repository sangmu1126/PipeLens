from pathlib import Path

from pipelens.models import (
    AnalysisRecord,
    AnalysisStatus,
    FeedbackAccuracy,
    FeedbackRequest,
    RelatedFile,
    TrustLevel,
)
from pipelens.store import AnalysisStore


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
    )

    saved = store.get(43)
    assert saved.related_files[0].filename == "src/app.py"
    assert saved.workflow_path == ".github/workflows/ci.yml"
    assert saved.model_name == "test-model"
    assert saved.prompt_version == "diagnosis-v1"


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

    store.update(47, AnalysisStatus.RUNNING, trust_level=TrustLevel.UNTRUSTED_FORK)

    assert store.get(47).trust_level is TrustLevel.UNTRUSTED_FORK
