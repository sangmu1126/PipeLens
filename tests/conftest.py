import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from pipelens.config import Settings
from pipelens.store import AnalysisStore


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer's local .env or PIPELENS_* shell variables must not leak into test settings.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.startswith("PIPELENS_") and not name.startswith("PIPELENS_TEST_"):
            monkeypatch.delenv(name)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AnalysisStore]:
    instance = AnalysisStore(str(tmp_path / "test.db"))
    instance.initialize()
    try:
        yield instance
    finally:
        instance.close()
