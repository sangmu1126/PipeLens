"""Restore a PostgreSQL backup in an isolated PostgreSQL 18 volume and emit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

PINNED_IMAGE_PATTERN = re.compile(r"^postgres:[^@\s]+@sha256:[0-9a-f]{64}$")
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
RELATION_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?$")

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def parse_count_expectation(value: str) -> tuple[str, int]:
    relation, separator, raw_count = value.partition("=")
    if not separator or not RELATION_PATTERN.fullmatch(relation):
        raise argparse.ArgumentTypeError("expected RELATION=MINIMUM with a safe relation name")
    try:
        minimum = int(raw_count)
    except ValueError as error:
        raise argparse.ArgumentTypeError("minimum count must be an integer") from error
    if minimum < 0:
        raise argparse.ArgumentTypeError("minimum count must be non-negative")
    return relation, minimum


def parse_utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("timestamp must be ISO 8601") from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote_relation(relation: str) -> str:
    if not RELATION_PATTERN.fullmatch(relation):
        raise ValueError(f"unsafe relation name: {relation}")
    return ".".join(f'"{part}"' for part in relation.split("."))


def alembic_heads(config_path: Path) -> list[str]:
    config = Config(str(config_path))
    return sorted(ScriptDirectory.from_config(config).get_heads())


def validate_args(args: argparse.Namespace) -> None:
    if not PINNED_IMAGE_PATTERN.fullmatch(args.image):
        raise ValueError("--image must be postgres:TAG@sha256:DIGEST")
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise ValueError("--run-id must contain only lowercase letters, digits, and hyphens")
    for path, label in (
        (args.backup, "--backup"),
        (args.password_file, "--password-file"),
        (args.alembic_config, "--alembic-config"),
    ):
        if not path.is_file():
            raise ValueError(f"{label} must be an existing regular file")
        if "," in str(path):
            raise ValueError(f"{label} path cannot contain a comma")
    if args.backup.stat().st_size == 0:
        raise ValueError("--backup cannot be empty")
    if args.password_file.stat().st_size == 0:
        raise ValueError("--password-file cannot be empty")
    if args.backup_duration_seconds <= 0:
        raise ValueError("--backup-duration-seconds must be positive")
    if args.rto_seconds <= 0 or args.rpo_seconds < 0 or args.observed_rpo_seconds < 0:
        raise ValueError("RTO must be positive and RPO values must be non-negative")
    if args.backup_created_at < args.write_freeze_at:
        raise ValueError("--backup-created-at cannot precede --write-freeze-at")
    if args.backup_created_at > datetime.now(UTC):
        raise ValueError("--backup-created-at cannot be in the future")
    if not args.expect_min_count:
        raise ValueError("at least one --expect-min-count is required")
    if len({relation for relation, _ in args.expect_min_count}) != len(args.expect_min_count):
        raise ValueError("each expected relation may be specified only once")


def docker_object_exists(kind: str, name: str, runner: CommandRunner) -> bool:
    result = runner(
        ["docker", kind, "inspect", name],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def query_scalar(
    container: str,
    database: str,
    database_user: str,
    query: str,
    runner: CommandRunner,
) -> str:
    result = runner(
        [
            "docker",
            "exec",
            container,
            "psql",
            "--username",
            database_user,
            "--dbname",
            database,
            "--tuples-only",
            "--no-align",
            "--set",
            "ON_ERROR_STOP=1",
            "--command",
            query,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def wait_for_postgres(
    container: str,
    database: str,
    database_user: str,
    runner: CommandRunner,
    *,
    attempts: int = 90,
) -> None:
    last_logs = ""
    for _ in range(attempts):
        logs_result = runner(
            ["docker", "logs", container], check=False, capture_output=True, text=True
        )
        last_logs = logs_result.stdout + logs_result.stderr
        if "PostgreSQL init process complete; ready for start up." not in last_logs:
            time.sleep(1)
            continue
        result = runner(
            ["docker", "exec", container, "pg_isready", "-U", database_user, "-d", database],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError(f"PostgreSQL did not finish initialization: {last_logs[-2000:]}")


def cleanup(container: str, volume: str, runner: CommandRunner) -> None:
    if docker_object_exists("container", container, runner):
        runner(
            ["docker", "rm", "--force", container],
            check=True,
            capture_output=True,
            text=True,
        )
    if docker_object_exists("volume", volume, runner):
        runner(
            ["docker", "volume", "rm", volume],
            check=True,
            capture_output=True,
            text=True,
        )


def run_drill(
    args: argparse.Namespace, runner: CommandRunner = subprocess.run
) -> dict[str, object]:
    validate_args(args)
    container = f"pipelens-postgres-restore-{args.run_id}"
    volume = f"pipelens-postgres-restore-{args.run_id}-data"
    for kind, name in (("container", container), ("volume", volume)):
        if docker_object_exists(kind, name, runner):
            raise RuntimeError(f"refusing to replace existing Docker {kind}: {name}")

    expected_heads = alembic_heads(args.alembic_config)
    backup_size = args.backup.stat().st_size
    backup_checksum = sha256_file(args.backup)
    recovery_started = time.monotonic()
    restore_seconds = 0.0
    succeeded = False
    try:
        runner(
            ["docker", "pull", args.image],
            check=True,
            capture_output=True,
            text=True,
        )
        runner(
            ["docker", "volume", "create", volume],
            check=True,
            capture_output=True,
            text=True,
        )
        runner(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                container,
                "--env",
                f"POSTGRES_DB={args.database}",
                "--env",
                f"POSTGRES_USER={args.database_user}",
                "--env",
                "POSTGRES_PASSWORD_FILE=/run/secrets/postgres-password",
                "--mount",
                f"type=volume,source={volume},target=/var/lib/postgresql",
                "--mount",
                f"type=bind,source={args.backup.resolve()},target=/evidence/backup.dump,readonly",
                "--mount",
                "type=bind,"
                f"source={args.password_file.resolve()},"
                "target=/run/secrets/postgres-password,readonly",
                args.image,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        wait_for_postgres(container, args.database, args.database_user, runner)

        runner(
            ["docker", "exec", container, "pg_restore", "--list", "/evidence/backup.dump"],
            check=True,
            capture_output=True,
            text=True,
        )
        restore_started = time.monotonic()
        restore_result = runner(
            [
                "docker",
                "exec",
                container,
                "pg_restore",
                "--username",
                args.database_user,
                "--dbname",
                args.database,
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "/evidence/backup.dump",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if restore_result.returncode != 0:
            detail = (restore_result.stderr or restore_result.stdout).strip()
            raise RuntimeError(f"pg_restore failed: {detail[-2000:]}")
        restore_seconds = time.monotonic() - restore_started

        server_version_num = int(
            query_scalar(
                container,
                args.database,
                args.database_user,
                "SHOW server_version_num;",
                runner,
            )
        )
        if not 180000 <= server_version_num < 190000:
            raise RuntimeError(f"restored server is not PostgreSQL 18: {server_version_num}")

        actual_heads_raw = query_scalar(
            container,
            args.database,
            args.database_user,
            "SELECT version_num FROM alembic_version ORDER BY version_num;",
            runner,
        )
        actual_heads = sorted(line for line in actual_heads_raw.splitlines() if line)
        if actual_heads != expected_heads:
            raise RuntimeError(
                f"Alembic head mismatch: expected {expected_heads}, restored {actual_heads}"
            )

        counts: dict[str, dict[str, int | bool]] = {}
        for relation, minimum in args.expect_min_count:
            actual = int(
                query_scalar(
                    container,
                    args.database,
                    args.database_user,
                    f"SELECT count(*) FROM {quote_relation(relation)};",
                    runner,
                )
            )
            counts[relation] = {"actual": actual, "minimum": minimum, "met": actual >= minimum}
            if actual < minimum:
                raise RuntimeError(
                    f"representative record check failed for {relation}: {actual} < {minimum}"
                )

        database_bytes = int(
            query_scalar(
                container,
                args.database,
                args.database_user,
                "SELECT pg_database_size(current_database());",
                runner,
            )
        )
        recovery_seconds = time.monotonic() - recovery_started
        succeeded = True
        return {
            "schema_version": 1,
            "checked_at": datetime.now(UTC).isoformat(),
            "source": {
                "revision": args.source_revision,
                "write_freeze_at": args.write_freeze_at.isoformat(),
                "backup_created_at": args.backup_created_at.isoformat(),
            },
            "objectives_seconds": {"rto": args.rto_seconds, "rpo": args.rpo_seconds},
            "backup": {
                "bytes": backup_size,
                "sha256": backup_checksum,
                "duration_seconds": round(args.backup_duration_seconds, 3),
            },
            "restore": {
                "image": args.image,
                "postgres_major": server_version_num // 10000,
                "duration_seconds": round(restore_seconds, 3),
                "recovery_duration_seconds": round(recovery_seconds, 3),
                "database_bytes": database_bytes,
                "rto_met": recovery_seconds <= args.rto_seconds,
                "observed_rpo_seconds": round(args.observed_rpo_seconds, 3),
                "rpo_met": args.observed_rpo_seconds <= args.rpo_seconds,
            },
            "integrity": {
                "alembic_heads": actual_heads,
                "representative_counts": counts,
                "backup_list_readable": True,
            },
            "target_preserved": args.preserve_target,
        }
    finally:
        if not args.preserve_target or not succeeded:
            cleanup(container, volume, runner)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="pinned PostgreSQL 18 image")
    parser.add_argument("--backup", type=Path, required=True, help="custom-format pg_dump")
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--database", default="pipelens")
    parser.add_argument("--database-user", default="pipelens")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--write-freeze-at", type=parse_utc_timestamp, required=True)
    parser.add_argument("--backup-created-at", type=parse_utc_timestamp, required=True)
    parser.add_argument("--backup-duration-seconds", type=float, required=True)
    parser.add_argument("--rto-seconds", type=float, required=True)
    parser.add_argument("--rpo-seconds", type=float, required=True)
    parser.add_argument("--observed-rpo-seconds", type=float, required=True)
    parser.add_argument(
        "--expect-min-count",
        action="append",
        type=parse_count_expectation,
        default=[],
        metavar="RELATION=MINIMUM",
    )
    parser.add_argument("--alembic-config", type=Path, default=Path("alembic.ini"))
    parser.add_argument("--run-id", default=f"{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:8]}")
    parser.add_argument("--preserve-target", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    evidence = run_drill(args)
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
