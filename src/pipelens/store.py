from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.exc import IntegrityError

from pipelens.models import (
    AnalysisRecord,
    AnalysisRequest,
    AnalysisStage,
    AnalysisStageEvent,
    AnalysisStatus,
    Classification,
    Diagnosis,
    ErrorCategory,
    ExecutionContext,
    FeedbackRecord,
    FeedbackRequest,
    GitHubInstallation,
    GitHubUser,
    RelatedFile,
    StageStatus,
    TrustLevel,
)

metadata = MetaData()


class AnalysisAttemptSuperseded(RuntimeError):
    pass


@dataclass(frozen=True)
class AnalysisStart:
    attempt_started_at: datetime
    queue_wait_seconds: float
    first_start: bool

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
    Column("trust_level", String(32), nullable=False, default=TrustLevel.TRUSTED.value),
    Column("baseline_sha", String(64)),
    Column("status", String(32), nullable=False, index=True),
    Column("classification", JSON),
    Column("diagnosis", JSON),
    Column("related_files", JSON, nullable=False, default=list),
    Column("workflow_path", Text),
    Column("execution_context", JSON),
    Column("model_name", String(255)),
    Column("prompt_version", String(255)),
    Column("error", Text),
    Column("analysis_started_at", DateTime(timezone=True)),
    Column("analysis_completed_at", DateTime(timezone=True)),
    Column("duration_seconds", Float),
    Column("queue_wait_seconds", Float),
    Column("total_latency_seconds", Float),
    Column("attempt_token", String(64)),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

analysis_stage_events = Table(
    "analysis_stage_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "run_id",
        BigInteger,
        ForeignKey("analyses.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("stage", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("error", Text),
    Column("occurred_at", DateTime(timezone=True), nullable=False, index=True),
)

feedback = Table(
    "analysis_feedback",
    metadata,
    Column(
        "run_id",
        BigInteger,
        ForeignKey("analyses.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("accuracy", String(32)),
    Column("suggestion_resolved", Boolean),
    Column("comment", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

github_users = Table(
    "github_users",
    metadata,
    Column("github_user_id", BigInteger, primary_key=True),
    Column("login", String(255), nullable=False),
    Column("avatar_url", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

auth_sessions = Table(
    "auth_sessions",
    metadata,
    Column("session_hash", String(64), primary_key=True),
    Column(
        "github_user_id",
        BigInteger,
        ForeignKey("github_users.github_user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("encrypted_access_token", Text, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

user_installations = Table(
    "user_installations",
    metadata,
    Column(
        "github_user_id",
        BigInteger,
        ForeignKey("github_users.github_user_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("installation_id", BigInteger, primary_key=True),
    Column("account_login", String(255), nullable=False),
    Column("account_type", String(64), nullable=False),
    Column("repository_selection", String(64), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("github_user_id", "installation_id"),
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

    def healthcheck(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()

    def create_if_absent(self, record: AnalysisRecord) -> bool:
        values = {
            "run_id": record.run_id,
            "delivery_id": record.delivery_id,
            "repository": record.repository,
            "workflow_name": record.workflow_name,
            "head_sha": record.head_sha,
            "html_url": record.html_url,
            "installation_id": record.installation_id,
            "trust_level": record.trust_level.value,
            "baseline_sha": record.baseline_sha,
            "status": record.status.value,
            "classification": _dump_model(record.classification),
            "diagnosis": _dump_model(record.diagnosis),
            "related_files": [item.model_dump(mode="json") for item in record.related_files],
            "workflow_path": record.workflow_path,
            "execution_context": _dump_model(record.execution_context),
            "model_name": record.model_name,
            "prompt_version": record.prompt_version,
            "error": record.error,
            "analysis_started_at": record.analysis_started_at,
            "analysis_completed_at": record.analysis_completed_at,
            "duration_seconds": record.duration_seconds,
            "queue_wait_seconds": record.queue_wait_seconds,
            "total_latency_seconds": record.total_latency_seconds,
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
        execution_context: ExecutionContext | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
        trust_level: TrustLevel | None = None,
        baseline_sha: str | None = None,
        error: str | None = None,
        attempt_token: str | None = None,
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
        if execution_context is not None:
            values["execution_context"] = execution_context.model_dump(mode="json")
        if model_name is not None:
            values["model_name"] = model_name
        if prompt_version is not None:
            values["prompt_version"] = prompt_version
        if trust_level is not None:
            values["trust_level"] = trust_level.value
        if baseline_sha is not None:
            values["baseline_sha"] = baseline_sha
        with self.engine.begin() as connection:
            statement = update(analyses).where(analyses.c.run_id == run_id)
            if attempt_token is not None:
                statement = statement.where(analyses.c.attempt_token == attempt_token)
            result = connection.execute(statement.values(**values))
            self._require_current_attempt(result.rowcount, run_id, attempt_token)

    def get(
        self, run_id: int, installation_ids: set[int] | None = None
    ) -> AnalysisRecord | None:
        statement = _analysis_select().where(analyses.c.run_id == run_id)
        if installation_ids is not None:
            if not installation_ids:
                return None
            statement = statement.where(analyses.c.installation_id.in_(installation_ids))
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
            stages = self._stage_history(connection, [run_id]).get(run_id, []) if row else []
        return self._to_record(row, stages) if row else None

    def list(
        self,
        limit: int = 50,
        installation_ids: set[int] | None = None,
        *,
        repository: str | None = None,
        status: AnalysisStatus | None = None,
        category: ErrorCategory | None = None,
    ) -> list[AnalysisRecord]:
        if installation_ids is not None and not installation_ids:
            return []
        statement = _analysis_select()
        if installation_ids is not None:
            statement = statement.where(analyses.c.installation_id.in_(installation_ids))
        if repository is not None:
            statement = statement.where(analyses.c.repository == repository)
        if status is not None:
            statement = statement.where(analyses.c.status == status.value)
        if category is not None:
            statement = statement.where(
                analyses.c.classification["category"].as_string() == category.value
            )
        statement = statement.order_by(analyses.c.created_at.desc()).limit(limit)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
            stages = self._stage_history(connection, [row["run_id"] for row in rows])
        return [self._to_record(row, stages.get(row["run_id"], [])) for row in rows]

    def queued_requests(self) -> list[AnalysisRequest]:
        statement = (
            select(
                analyses.c.run_id,
                analyses.c.repository,
                analyses.c.installation_id,
                analyses.c.head_sha,
            )
            .where(
                analyses.c.status == AnalysisStatus.QUEUED.value,
                analyses.c.installation_id.is_not(None),
            )
            .order_by(analyses.c.created_at)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [AnalysisRequest.model_validate(dict(row)) for row in rows]

    def begin_analysis(self, run_id: int, attempt_token: str | None = None) -> AnalysisStart:
        started_at = datetime.now(UTC)
        with self.engine.begin() as connection:
            timing = connection.execute(
                select(
                    analyses.c.created_at,
                    analyses.c.analysis_started_at,
                    analyses.c.queue_wait_seconds,
                ).where(analyses.c.run_id == run_id)
            ).mappings().one_or_none()
            if timing is None:
                raise AnalysisAttemptSuperseded(f"analysis run {run_id} does not exist")
            first_start = timing["analysis_started_at"] is None
            queue_wait = timing["queue_wait_seconds"]
            if queue_wait is None:
                created_at = _as_utc(timing["created_at"])
                queue_wait = max(0.0, (started_at - created_at).total_seconds())
            statement = update(analyses).where(analyses.c.run_id == run_id)
            if attempt_token is not None:
                statement = statement.where(
                    analyses.c.status.in_(
                        [AnalysisStatus.QUEUED.value, AnalysisStatus.RUNNING.value]
                    )
                )
            result = connection.execute(
                statement.values(
                    status=AnalysisStatus.RUNNING.value,
                    error=None,
                    attempt_token=attempt_token,
                    analysis_started_at=timing["analysis_started_at"] or started_at,
                    analysis_completed_at=None,
                    duration_seconds=None,
                    queue_wait_seconds=queue_wait,
                    total_latency_seconds=None,
                    updated_at=started_at,
                )
            )
            self._require_current_attempt(result.rowcount, run_id, attempt_token)
            if attempt_token is not None:
                connection.execute(
                    update(analysis_stage_events)
                    .where(
                        analysis_stage_events.c.run_id == run_id,
                        analysis_stage_events.c.status == StageStatus.STARTED.value,
                    )
                    .values(
                        status=StageStatus.FAILED.value,
                        error="Superseded by a newer analysis attempt",
                    )
                )
        return AnalysisStart(started_at, queue_wait, first_start)

    def finish_analysis(
        self,
        run_id: int,
        started_at: datetime,
        status: AnalysisStatus = AnalysisStatus.COMPLETED,
        attempt_token: str | None = None,
    ) -> float:
        completed_at = datetime.now(UTC)
        with self.engine.begin() as connection:
            created_at = connection.scalar(
                select(analyses.c.created_at).where(analyses.c.run_id == run_id)
            )
            if created_at is None:
                raise AnalysisAttemptSuperseded(f"analysis run {run_id} does not exist")
            total_latency = max(0.0, (completed_at - _as_utc(created_at)).total_seconds())
            statement = update(analyses).where(analyses.c.run_id == run_id)
            if attempt_token is not None:
                statement = statement.where(analyses.c.attempt_token == attempt_token)
            result = connection.execute(
                statement.values(
                    status=status.value,
                    attempt_token=None,
                    analysis_completed_at=completed_at,
                    duration_seconds=(completed_at - started_at).total_seconds(),
                    total_latency_seconds=total_latency,
                    updated_at=completed_at,
                )
            )
            self._require_current_attempt(result.rowcount, run_id, attempt_token)
        return total_latency

    def record_stage(
        self,
        run_id: int,
        stage: AnalysisStage,
        status: StageStatus,
        error: str | None = None,
        attempt_token: str | None = None,
    ) -> None:
        with self.engine.begin() as connection:
            if attempt_token is not None:
                current = connection.execute(
                    select(analyses.c.run_id).where(
                        analyses.c.run_id == run_id,
                        analyses.c.attempt_token == attempt_token,
                    )
                ).first()
                if current is None:
                    raise AnalysisAttemptSuperseded(
                        f"analysis attempt for run {run_id} is no longer current"
                    )
            connection.execute(
                insert(analysis_stage_events).values(
                    run_id=run_id,
                    stage=stage.value,
                    status=status.value,
                    error=error,
                    occurred_at=datetime.now(UTC),
                )
            )

    @staticmethod
    def _require_current_attempt(
        rowcount: int, run_id: int, attempt_token: str | None
    ) -> None:
        if attempt_token is not None and rowcount != 1:
            raise AnalysisAttemptSuperseded(
                f"analysis attempt for run {run_id} is no longer current"
            )

    def save_feedback(
        self,
        run_id: int,
        request: FeedbackRequest,
        installation_ids: set[int] | None = None,
    ) -> FeedbackRecord | None:
        now = datetime.now(UTC)
        values = {
            "accuracy": request.accuracy.value if request.accuracy else None,
            "suggestion_resolved": request.suggestion_resolved,
            "comment": request.comment,
            "updated_at": now,
        }
        analysis_statement = select(analyses.c.run_id).where(analyses.c.run_id == run_id)
        if installation_ids is not None:
            if not installation_ids:
                return None
            analysis_statement = analysis_statement.where(
                analyses.c.installation_id.in_(installation_ids)
            )
        with self.engine.begin() as connection:
            if connection.execute(analysis_statement).first() is None:
                return None
            existing = connection.execute(
                select(feedback.c.run_id).where(feedback.c.run_id == run_id)
            ).first()
            if existing:
                connection.execute(
                    update(feedback).where(feedback.c.run_id == run_id).values(**values)
                )
            else:
                connection.execute(insert(feedback).values(run_id=run_id, created_at=now, **values))
            row = (
                connection.execute(select(feedback).where(feedback.c.run_id == run_id))
                .mappings()
                .one()
            )
        return FeedbackRecord.model_validate(dict(row))

    def delete(self, run_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(delete(analyses).where(analyses.c.run_id == run_id))

    def upsert_github_user(self, user: GitHubUser) -> None:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            exists = connection.execute(
                select(github_users.c.github_user_id).where(
                    github_users.c.github_user_id == user.github_user_id
                )
            ).first()
            values = {"login": user.login, "avatar_url": user.avatar_url, "updated_at": now}
            if exists:
                connection.execute(
                    update(github_users)
                    .where(github_users.c.github_user_id == user.github_user_id)
                    .values(**values)
                )
            else:
                connection.execute(
                    insert(github_users).values(
                        github_user_id=user.github_user_id, created_at=now, **values
                    )
                )

    def replace_user_installations(
        self, github_user_id: int, installations: list[GitHubInstallation]
    ) -> None:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            connection.execute(
                delete(user_installations).where(
                    user_installations.c.github_user_id == github_user_id
                )
            )
            if installations:
                connection.execute(
                    insert(user_installations),
                    [
                        {
                            "github_user_id": github_user_id,
                            **installation.model_dump(),
                            "updated_at": now,
                        }
                        for installation in installations
                    ],
                )

    def create_auth_session(
        self,
        session_hash: str,
        github_user_id: int,
        encrypted_access_token: str,
        expires_at: datetime,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(auth_sessions).values(
                    session_hash=session_hash,
                    github_user_id=github_user_id,
                    encrypted_access_token=encrypted_access_token,
                    expires_at=expires_at,
                    created_at=datetime.now(UTC),
                )
            )

    def get_auth_session(self, session_hash: str) -> dict | None:
        statement = (
            select(
                auth_sessions.c.github_user_id,
                auth_sessions.c.encrypted_access_token,
                auth_sessions.c.expires_at,
                github_users.c.login,
                github_users.c.avatar_url,
            )
            .select_from(
                auth_sessions.join(
                    github_users,
                    auth_sessions.c.github_user_id == github_users.c.github_user_id,
                )
            )
            .where(auth_sessions.c.session_hash == session_hash)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return dict(row) if row else None

    def delete_auth_session(self, session_hash: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                delete(auth_sessions).where(auth_sessions.c.session_hash == session_hash)
            )

    def installations_for_user(self, github_user_id: int) -> list[GitHubInstallation]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        user_installations.c.installation_id,
                        user_installations.c.account_login,
                        user_installations.c.account_type,
                        user_installations.c.repository_selection,
                    )
                    .where(user_installations.c.github_user_id == github_user_id)
                    .order_by(user_installations.c.account_login)
                )
                .mappings()
                .all()
            )
        return [GitHubInstallation.model_validate(dict(row)) for row in rows]

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _stage_history(connection, run_ids: list[int]) -> dict[int, list[AnalysisStageEvent]]:
        if not run_ids:
            return {}
        rows = (
            connection.execute(
                select(analysis_stage_events)
                .where(analysis_stage_events.c.run_id.in_(run_ids))
                .order_by(analysis_stage_events.c.id)
            )
            .mappings()
            .all()
        )
        result: dict[int, list[AnalysisStageEvent]] = {run_id: [] for run_id in run_ids}
        for row in rows:
            values = dict(row)
            run_id = values.pop("run_id")
            values.pop("id")
            result[run_id].append(AnalysisStageEvent.model_validate(values))
        return result

    @staticmethod
    def _to_record(
        row: RowMapping, stage_history: list[AnalysisStageEvent]
    ) -> AnalysisRecord:
        values = dict(row)
        feedback_run_id = values.pop("feedback_run_id")
        feedback_values = {
            "run_id": feedback_run_id,
            "accuracy": values.pop("feedback_accuracy"),
            "suggestion_resolved": values.pop("feedback_suggestion_resolved"),
            "comment": values.pop("feedback_comment"),
            "created_at": values.pop("feedback_created_at"),
            "updated_at": values.pop("feedback_updated_at"),
        }
        values["feedback"] = (
            FeedbackRecord.model_validate(feedback_values) if feedback_run_id else None
        )
        values["stage_history"] = stage_history
        return AnalysisRecord.model_validate(values)


def _dump_model(
    value: Classification | Diagnosis | ExecutionContext | None,
) -> dict | None:
    return value.model_dump(mode="json") if value is not None else None


def _normalize_database_url(value: str) -> str:
    return value if "://" in value else f"sqlite:///{value}"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _analysis_select():
    return select(
        *analyses.c,
        feedback.c.run_id.label("feedback_run_id"),
        feedback.c.accuracy.label("feedback_accuracy"),
        feedback.c.suggestion_resolved.label("feedback_suggestion_resolved"),
        feedback.c.comment.label("feedback_comment"),
        feedback.c.created_at.label("feedback_created_at"),
        feedback.c.updated_at.label("feedback_updated_at"),
    ).select_from(analyses.outerjoin(feedback, analyses.c.run_id == feedback.c.run_id))
