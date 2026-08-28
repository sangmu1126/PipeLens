from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from pipelens.store import analyses


def test_initial_migration_upgrades_and_downgrades_sqlite(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("PIPELENS_DATABASE_URL", database_url)
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert {
        "analyses",
        "analysis_feedback",
        "github_users",
        "auth_sessions",
        "user_installations",
    } <= set(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("analyses")} >= {
        "run_id",
        "classification",
        "diagnosis",
        "related_files",
        "model_name",
        "prompt_version",
        "trust_level",
        "baseline_sha",
        "analysis_started_at",
        "analysis_completed_at",
        "duration_seconds",
    }
    assert "analysis_stage_events" in inspector.get_table_names()
    command.check(config)

    command.downgrade(config, "base")
    assert "analyses" not in inspect(engine).get_table_names()
    assert "analysis_feedback" not in inspect(engine).get_table_names()
    assert "analysis_stage_events" not in inspect(engine).get_table_names()
    engine.dispose()


def test_analysis_table_compiles_for_postgresql() -> None:
    statement = str(CreateTable(analyses).compile(dialect=postgresql.dialect()))

    assert "CREATE TABLE analyses" in statement
    assert "JSON" in statement
    assert "delivery_id VARCHAR(255) NOT NULL" in statement
