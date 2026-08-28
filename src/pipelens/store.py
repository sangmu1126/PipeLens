import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from pipelens.models import AnalysisRecord, AnalysisStatus, Classification, Diagnosis, RelatedFile


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
                    related_files TEXT NOT NULL DEFAULT '[]',
                    workflow_path TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(analyses)").fetchall()
            }
            if "related_files" not in columns:
                connection.execute(
                    "ALTER TABLE analyses ADD COLUMN related_files TEXT NOT NULL DEFAULT '[]'"
                )
            if "workflow_path" not in columns:
                connection.execute("ALTER TABLE analyses ADD COLUMN workflow_path TEXT")
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
        related_files: list[RelatedFile] | None = None,
        workflow_path: str | None = None,
        error: str | None = None,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE analyses
                SET status = ?, classification = COALESCE(?, classification),
                    diagnosis = COALESCE(?, diagnosis),
                    related_files = COALESCE(?, related_files),
                    workflow_path = COALESCE(?, workflow_path),
                    error = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    status.value,
                    classification.model_dump_json() if classification else None,
                    diagnosis.model_dump_json() if diagnosis else None,
                    json.dumps([item.model_dump() for item in related_files])
                    if related_files is not None
                    else None,
                    workflow_path,
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
        values["related_files"] = [
            RelatedFile.model_validate(item)
            for item in json.loads(values.get("related_files") or "[]")
        ]
        return AnalysisRecord.model_validate(values)
