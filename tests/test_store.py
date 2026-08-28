from pathlib import Path

from pipelens.models import AnalysisRecord, AnalysisStatus
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
