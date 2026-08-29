import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from pipelens.models import AnalysisRecord
from pipelens.store import AnalysisStore


def _test_database_url() -> str:
    database_url = os.getenv("PIPELENS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PIPELENS_TEST_DATABASE_URL is not configured")
    if not (make_url(database_url).database or "").endswith("_test"):
        pytest.fail("integration migrations require a database name ending in '_test'")
    return database_url


def test_postgres_migrations_and_analysis_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _test_database_url()
    monkeypatch.setenv("PIPELENS_DATABASE_URL", database_url)
    alembic = Config("alembic.ini")

    command.upgrade(alembic, "head")
    command.check(alembic)

    unique_id = uuid.uuid4().int
    run_id = unique_id % (2**63 - 1)
    store = AnalysisStore(database_url)
    try:
        store.healthcheck()
        assert store.create_if_absent(
            AnalysisRecord(
                run_id=run_id,
                delivery_id=f"integration-{unique_id}",
                repository="pipelens/integration",
                workflow_name="Integration CI",
                head_sha="a" * 40,
                html_url=f"https://github.com/pipelens/integration/actions/runs/{run_id}",
                installation_id=1,
            )
        )

        start = store.begin_analysis(run_id, "integration-attempt")
        total_latency = store.finish_analysis(
            run_id,
            start.attempt_started_at,
            attempt_token="integration-attempt",
        )
        saved = store.get(run_id)

        assert saved is not None
        assert saved.queue_wait_seconds is not None
        assert saved.total_latency_seconds == total_latency
    finally:
        store.close()
