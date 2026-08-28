from pathlib import Path

from pipelens.models import AnalysisRecord, AnalysisStatus, RelatedFile
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
    )

    saved = store.get(43)
    assert saved.related_files[0].filename == "src/app.py"
    assert saved.workflow_path == ".github/workflows/ci.yml"
