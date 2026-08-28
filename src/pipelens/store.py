from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.exc import IntegrityError

from pipelens.models import AnalysisRecord, AnalysisStatus, Classification, Diagnosis, RelatedFile

metadata = MetaData()

analyses = Table(
    "analyses",
    metadata,
    Column("run_id", BigInteger, primary_key=True),
    Column("delivery_id", String(255), nullable=False, unique=True),
    Column("repository", String(255), nullable=False, index=True),
    Column("workflow_name", String(255), nullable=False),
    Column("head_sha", String(64), nullable=False),
    Column("html_url", Text, nullable=False),
    Column("installation_id", BigInteger),
    Column("status", String(32), nullable=False, index=True),
    Column("classification", JSON),
    Column("diagnosis", JSON),
    Column("related_files", JSON, nullable=False, default=list),
    Column("workflow_path", Text),
    Column("model_name", String(255)),
    Column("prompt_version", String(255)),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


class AnalysisStore:
    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self.database_url = _normalize_database_url(database_url)
        self.engine = engine or create_engine(self.database_url, pool_pre_ping=True)

    @property
    def database_path(self) -> str:
        """Compatibility helper for local SQLite callers."""
        if self.engine.url.get_backend_name() != "sqlite":
            return self.database_url
        return self.engine.url.database or ":memory:"

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def create_if_absent(self, record: AnalysisRecord) -> bool:
        values = {
            "run_id": record.run_id,
            "delivery_id": record.delivery_id,
            "repository": record.repository,
            "workflow_name": record.workflow_name,
            "head_sha": record.head_sha,
            "html_url": record.html_url,
            "installation_id": record.installation_id,
            "status": record.status.value,
            "classification": _dump_model(record.classification),
            "diagnosis": _dump_model(record.diagnosis),
            "related_files": [item.model_dump(mode="json") for item in record.related_files],
            "workflow_path": record.workflow_path,
            "model_name": record.model_name,
            "prompt_version": record.prompt_version,
            "error": record.error,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(analyses).values(**values))
        except IntegrityError:
            return False
        return True

    def update(
        self,
        run_id: int,
        status: AnalysisStatus,
        classification: Classification | None = None,
        diagnosis: Diagnosis | None = None,
        related_files: list[RelatedFile] | None = None,
        workflow_path: str | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
        error: str | None = None,
    ) -> None:
        values: dict = {
            "status": status.value,
            "error": error,
            "updated_at": datetime.now(UTC),
        }
        if classification is not None:
            values["classification"] = classification.model_dump(mode="json")
        if diagnosis is not None:
            values["diagnosis"] = diagnosis.model_dump(mode="json")
        if related_files is not None:
            values["related_files"] = [item.model_dump(mode="json") for item in related_files]
        if workflow_path is not None:
            values["workflow_path"] = workflow_path
        if model_name is not None:
            values["model_name"] = model_name
        if prompt_version is not None:
            values["prompt_version"] = prompt_version
        with self.engine.begin() as connection:
            connection.execute(update(analyses).where(analyses.c.run_id == run_id).values(**values))

    def get(self, run_id: int) -> AnalysisRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(analyses).where(analyses.c.run_id == run_id))
                .mappings()
                .first()
            )
        return self._to_record(row) if row else None

    def list(self, limit: int = 50) -> list[AnalysisRecord]:
        statement = select(analyses).order_by(analyses.c.created_at.desc()).limit(limit)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._to_record(row) for row in rows]

    def delete(self, run_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(delete(analyses).where(analyses.c.run_id == run_id))

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _to_record(row: RowMapping) -> AnalysisRecord:
        return AnalysisRecord.model_validate(dict(row))


def _dump_model(value: Classification | Diagnosis | None) -> dict | None:
    return value.model_dump(mode="json") if value is not None else None


def _normalize_database_url(value: str) -> str:
    return value if "://" in value else f"sqlite:///{value}"
