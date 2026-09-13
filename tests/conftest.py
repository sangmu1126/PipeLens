from collections.abc import Iterator
from pathlib import Path

import pytest

from pipelens.store import AnalysisStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AnalysisStore]:
    instance = AnalysisStore(str(tmp_path / "test.db"))
    instance.initialize()
    try:
        yield instance
    finally:
        instance.close()
