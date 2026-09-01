from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from ops.postgres.verify_restore import (
    alembic_heads,
    parse_args,
    parse_count_expectation,
    parse_utc_timestamp,
    quote_relation,
    run_drill,
    sha256_file,
    validate_args,
)

PINNED_IMAGE = "postgres:18-alpine@sha256:" + "a" * 64


def test_parse_count_expectation() -> None:
    assert parse_count_expectation("public.analyses=1200") == ("public.analyses", 1200)


@pytest.mark.parametrize(
    "value",
    ["analyses", "analyses=-1", "analyses=abc", "analyses;DROP TABLE users=1"],
)
def test_parse_count_expectation_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_count_expectation(value)


def test_timestamp_requires_offset_and_normalizes_to_utc() -> None:
    assert parse_utc_timestamp("2026-09-01T23:00:00+09:00").isoformat() == (
        "2026-09-01T14:00:00+00:00"
    )
    with pytest.raises(argparse.ArgumentTypeError):
        parse_utc_timestamp("2026-09-01T23:00:00")


def test_quote_relation() -> None:
    assert quote_relation("public.analyses") == '"public"."analyses"'
    with pytest.raises(ValueError, match="unsafe relation"):
        quote_relation("analyses; DELETE")


def test_sha256_file(tmp_path: Path) -> None:
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"pipelens")
    assert sha256_file(backup) == "c05ee90a0d83bc23d41d4d34ce3cf1540aa30514b79f6f32882d17093a0b0e79"


def test_parse_args_requires_operational_metadata(tmp_path: Path) -> None:
    backup = tmp_path / "backup.dump"
    password = tmp_path / "password"
    backup.write_bytes(b"dump")
    password.write_text("secret", encoding="utf-8")
    args = parse_args(
        [
            "--image",
            PINNED_IMAGE,
            "--backup",
            str(backup),
            "--password-file",
            str(password),
            "--source-revision",
            "release-2026-09-01",
            "--write-freeze-at",
            "2026-09-01T14:00:00Z",
            "--backup-created-at",
            "2026-09-01T14:01:00Z",
            "--backup-duration-seconds",
            "60",
            "--rto-seconds",
            "300",
            "--rpo-seconds",
            "60",
            "--observed-rpo-seconds",
            "45",
            "--expect-min-count",
            "analyses=1000",
            "--run-id",
            "production-20260901",
            "--output",
            str(tmp_path / "result.json"),
        ]
    )
    args.alembic_config = Path("alembic.ini")
    validate_args(args)
    assert args.expect_min_count == [("analyses", 1000)]


def test_validate_args_rejects_mutable_image_and_duplicate_relations(tmp_path: Path) -> None:
    backup = tmp_path / "backup.dump"
    password = tmp_path / "password"
    config = tmp_path / "alembic.ini"
    for path in (backup, password, config):
        path.write_text("value", encoding="utf-8")
    args = argparse.Namespace(
        image="postgres:18-alpine",
        run_id="restore-test",
        backup=backup,
        password_file=password,
        alembic_config=config,
        backup_duration_seconds=1,
        rto_seconds=10,
        rpo_seconds=0,
        observed_rpo_seconds=0,
        write_freeze_at=parse_utc_timestamp("2026-09-01T14:00:00Z"),
        backup_created_at=parse_utc_timestamp("2026-09-01T14:01:00Z"),
        expect_min_count=[("analyses", 1), ("analyses", 2)],
    )
    with pytest.raises(ValueError, match="image"):
        validate_args(args)

    args.image = PINNED_IMAGE
    with pytest.raises(ValueError, match="only once"):
        validate_args(args)


def test_run_drill_emits_redacted_evidence_and_cleans_target(tmp_path: Path) -> None:
    backup = tmp_path / "production.dump"
    password = tmp_path / "password"
    backup.write_bytes(b"custom-format-backup")
    password.write_text("super-secret", encoding="utf-8")
    args = parse_args(
        [
            "--image",
            PINNED_IMAGE,
            "--backup",
            str(backup),
            "--password-file",
            str(password),
            "--source-revision",
            "release-2026-09-01",
            "--write-freeze-at",
            "2025-09-01T14:00:00Z",
            "--backup-created-at",
            "2025-09-01T14:01:00Z",
            "--backup-duration-seconds",
            "60",
            "--rto-seconds",
            "300",
            "--rpo-seconds",
            "60",
            "--observed-rpo-seconds",
            "45",
            "--expect-min-count",
            "analyses=10",
            "--run-id",
            "production-test",
            "--output",
            str(tmp_path / "evidence.json"),
        ]
    )
    containers: set[str] = set()
    volumes: set[str] = set()

    def fake_runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        stdout = ""
        returncode = 0
        if command[1:3] == ["container", "inspect"]:
            returncode = 0 if command[3] in containers else 1
        elif command[1:3] == ["volume", "inspect"]:
            returncode = 0 if command[3] in volumes else 1
        elif command[1:3] == ["volume", "create"]:
            volumes.add(command[3])
        elif command[1:3] == ["run", "--detach"]:
            containers.add(command[command.index("--name") + 1])
        elif command[1:3] == ["rm", "--force"]:
            containers.remove(command[3])
        elif command[1:4] == ["volume", "rm", "pipelens-postgres-restore-production-test-data"]:
            volumes.remove(command[3])
        elif "--command" in command:
            query = command[command.index("--command") + 1]
            if query == "SHOW server_version_num;":
                stdout = "180006\n"
            elif "FROM alembic_version" in query:
                stdout = "\n".join(alembic_heads(Path("alembic.ini"))) + "\n"
            elif "count(*)" in query:
                stdout = "42\n"
            elif "pg_database_size" in query:
                stdout = "123456\n"
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")

    evidence = run_drill(args, fake_runner)

    assert evidence["restore"]["rto_met"] is True  # type: ignore[index]
    assert evidence["restore"]["rpo_met"] is True  # type: ignore[index]
    assert evidence["integrity"]["representative_counts"]["analyses"] == {  # type: ignore[index]
        "actual": 42,
        "minimum": 10,
        "met": True,
    }
    assert str(backup) not in str(evidence)
    assert "super-secret" not in str(evidence)
    assert not containers
    assert not volumes
