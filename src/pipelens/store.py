import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from pipelens.models import AnalysisRecord, AnalysisStatus, Classification, Diagnosis


class AnalysisStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        path = Path(self.database_path)
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    run_id INTEGER PRIMARY KEY,
                    delivery_id TEXT NOT NULL UNIQUE,
                    repository TEXT NOT NULL,
                    workflow_name TEXT NOT NULL,
                    head_sha TEXT NOT NULL,
                    html_url TEXT NOT NULL,
                    installation_id INTEGER,
                    status TEXT NOT NULL,
                    classification TEXT,
                    diagnosis TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def create_if_absent(self, record: AnalysisRecord) -> bool:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO analyses
                (run_id, delivery_id, repository, workflow_name, head_sha, html_url,
                 installation_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.delivery_id,
                    record.repository,
                    record.workflow_name,
                    record.head_sha,
                    record.html_url,
                    record.installation_id,
                    record.status.value,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def update(
        self,
        run_id: int,
        status: AnalysisStatus,
        classification: Classification | None = None,
        diagnosis: Diagnosis | None = None,
        error: str | None = None,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE analyses
                SET status = ?, classification = COALESCE(?, classification),
                    diagnosis = COALESCE(?, diagnosis), error = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    status.value,
                    classification.model_dump_json() if classification else None,
                    diagnosis.model_dump_json() if diagnosis else None,
                    error,
                    datetime.now(UTC).isoformat(),
                    run_id,
                ),
            )
            connection.commit()

    def get(self, run_id: int) -> AnalysisRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM analyses WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def list(self, limit: int = 50) -> list[AnalysisRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._to_record(row) for row in rows]

    @staticmethod
    def _to_record(row: sqlite3.Row) -> AnalysisRecord:
        values = dict(row)
        values["classification"] = (
            Classification.model_validate(json.loads(values["classification"]))
            if values["classification"]
            else None
        )
        values["diagnosis"] = (
            Diagnosis.model_validate(json.loads(values["diagnosis"]))
            if values["diagnosis"]
            else None
        )
        return AnalysisRecord.model_validate(values)
