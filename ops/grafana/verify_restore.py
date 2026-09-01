"""Restore a Grafana backup in an isolated Grafana 13 volume and emit evidence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import tarfile
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

PINNED_IMAGE_PATTERN = re.compile(r"^grafana/grafana:[^@\s]+@sha256:[0-9a-f]{64}$")
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
UID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
ADMIN_USER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,254}$")

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
HttpGetter = Callable[[str, tuple[str, str] | None], tuple[int, bytes, str]]


def parse_named_expectation(value: str) -> tuple[str, str]:
    uid, separator, title = value.partition("=")
    if not separator or not UID_PATTERN.fullmatch(uid) or not title.strip():
        raise argparse.ArgumentTypeError("expected UID=TITLE")
    return uid, title.strip()


def parse_datasource_expectation(value: str) -> tuple[str, str, str]:
    uid, separator, remainder = value.partition("=")
    datasource_type, comma, url = remainder.partition(",")
    if (
        not separator
        or not comma
        or not UID_PATTERN.fullmatch(uid)
        or not datasource_type.strip()
        or not url.strip()
    ):
        raise argparse.ArgumentTypeError("expected UID=TYPE,URL")
    return uid, datasource_type.strip(), url.strip()


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


def inspect_archive(path: Path) -> dict[str, int]:
    member_count = 0
    uncompressed_bytes = 0
    database_bytes = 0
    try:
        with tarfile.open(path, "r:*") as archive:
            for member in archive.getmembers():
                normalized = member.name.removeprefix("./")
                member_path = PurePosixPath(normalized)
                if (
                    not normalized
                    or member_path.is_absolute()
                    or ".." in member_path.parts
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or member.isfifo()
                ):
                    raise ValueError(f"unsafe archive member: {member.name}")
                member_count += 1
                if member.isfile():
                    uncompressed_bytes += member.size
                if normalized == "grafana.db" and member.isfile():
                    database_bytes = member.size
    except tarfile.TarError as error:
        raise ValueError("--backup must be a readable tar archive") from error
    if database_bytes == 0:
        raise ValueError("backup archive must contain a non-empty root grafana.db")
    return {
        "member_count": member_count,
        "uncompressed_bytes": uncompressed_bytes,
        "database_bytes": database_bytes,
    }


def validate_args(args: argparse.Namespace) -> None:
    if not PINNED_IMAGE_PATTERN.fullmatch(args.image):
        raise ValueError("--image must be grafana/grafana:TAG@sha256:DIGEST")
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise ValueError("--run-id must contain only lowercase letters, digits, and hyphens")
    if not args.backup.is_file() or args.backup.stat().st_size == 0:
        raise ValueError("--backup must be an existing non-empty regular file")
    if "," in str(args.backup):
        raise ValueError("--backup path cannot contain a comma")
    if (args.provisioning_dir is None) != (args.dashboards_dir is None):
        raise ValueError("--provisioning-dir and --dashboards-dir must be provided together")
    for path, label in (
        (args.provisioning_dir, "--provisioning-dir"),
        (args.dashboards_dir, "--dashboards-dir"),
    ):
        if path is not None and (not path.is_dir() or "," in str(path)):
            raise ValueError(f"{label} must be an existing directory without a comma")
    if not args.admin_password_file.is_file():
        raise ValueError("--admin-password-file must be an existing regular file")
    if args.admin_password_file.stat().st_size > 1024 * 1024:
        raise ValueError("--admin-password-file cannot exceed 1 MiB")
    if not ADMIN_USER_PATTERN.fullmatch(args.admin_user):
        raise ValueError("--admin-user contains unsupported characters")
    try:
        admin_password = args.admin_password_file.read_text(encoding="utf-8").rstrip("\r\n")
    except UnicodeDecodeError as error:
        raise ValueError("--admin-password-file must contain UTF-8 text") from error
    if not admin_password:
        raise ValueError("--admin-password-file cannot be empty")
    if args.backup_duration_seconds <= 0:
        raise ValueError("--backup-duration-seconds must be positive")
    if args.rto_seconds <= 0 or args.rpo_seconds < 0 or args.observed_rpo_seconds < 0:
        raise ValueError("RTO must be positive and RPO values must be non-negative")
    if args.backup_created_at < args.write_freeze_at:
        raise ValueError("--backup-created-at cannot precede --write-freeze-at")
    if args.backup_created_at > datetime.now(UTC):
        raise ValueError("--backup-created-at cannot be in the future")
    if not args.expect_dashboard or not args.expect_folder or not args.expect_datasource:
        raise ValueError("dashboard, folder, and datasource expectations are all required")
    for expectations, label in (
        (args.expect_dashboard, "dashboard"),
        (args.expect_folder, "folder"),
        (args.expect_datasource, "datasource"),
    ):
        if len({expectation[0] for expectation in expectations}) != len(expectations):
            raise ValueError(f"each expected {label} UID may be specified only once")
    inspect_archive(args.backup)


def docker_object_exists(kind: str, name: str, runner: CommandRunner) -> bool:
    result = runner(
        ["docker", kind, "inspect", name],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def http_get(url: str, credentials: tuple[str, str] | None = None) -> tuple[int, bytes, str]:
    request = Request(url, method="GET")
    if credentials:
        token = base64.b64encode(f"{credentials[0]}:{credentials[1]}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urlopen(request, timeout=5) as response:  # noqa: S310
            return response.status, response.read(), response.headers.get_content_type()
    except HTTPError as error:
        return error.code, error.read(), error.headers.get_content_type()


def wait_for_grafana(
    origin: str,
    expected_version: str,
    getter: HttpGetter,
    *,
    attempts: int = 90,
) -> dict[str, Any]:
    for _ in range(attempts):
        try:
            status, body, _ = getter(f"{origin}/api/health", None)
            payload = json.loads(body)
            if (
                status == 200
                and payload.get("database") == "ok"
                and payload.get("version") == expected_version
            ):
                return payload
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise RuntimeError("Grafana did not become healthy with the expected version")


def get_json(
    origin: str,
    path: str,
    getter: HttpGetter,
    credentials: tuple[str, str] | None,
) -> dict[str, Any]:
    status, body, content_type = getter(f"{origin}{path}", credentials)
    if status != 200 or content_type != "application/json":
        raise RuntimeError(f"Grafana API request failed for {path}: HTTP {status}")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Grafana API returned a non-object for {path}")
    return payload


def validate_access_policy(
    origin: str,
    anonymous_role: str,
    probe_dashboard_uid: str,
    getter: HttpGetter,
    credentials: tuple[str, str],
) -> dict[str, object]:
    settings = get_json(origin, "/api/admin/settings", getter, credentials)
    anonymous_settings = settings.get("auth.anonymous", {})
    expected_enabled = anonymous_role != "disabled"
    enabled = str(anonymous_settings.get("enabled", "false")).lower() == "true"
    configured_role = anonymous_settings.get("org_role", "")
    if enabled != expected_enabled:
        raise RuntimeError("Grafana anonymous access enabled state does not match expectation")
    if expected_enabled and configured_role != anonymous_role:
        raise RuntimeError("Grafana anonymous role does not match expectation")

    dashboard_status, _, _ = getter(
        f"{origin}/api/dashboards/uid/{quote(probe_dashboard_uid, safe='')}", None
    )
    admin_status, _, _ = getter(f"{origin}/api/admin/settings", None)
    anonymous_dashboard_allowed = dashboard_status == 200
    if anonymous_dashboard_allowed != expected_enabled or admin_status not in {401, 403}:
        raise RuntimeError("Grafana anonymous API access policy check failed")
    return {
        "anonymous_enabled": enabled,
        "anonymous_role": anonymous_role if enabled else "disabled",
        "anonymous_dashboard_allowed": anonymous_dashboard_allowed,
        "anonymous_admin_denied": True,
    }


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
    args: argparse.Namespace,
    runner: CommandRunner = subprocess.run,
    getter: HttpGetter = http_get,
) -> dict[str, object]:
    validate_args(args)
    archive = inspect_archive(args.backup)
    container = f"pipelens-grafana-restore-{args.run_id}"
    volume = f"pipelens-grafana-restore-{args.run_id}-data"
    for kind, name in (("container", container), ("volume", volume)):
        if docker_object_exists(kind, name, runner):
            raise RuntimeError(f"refusing to replace existing Docker {kind}: {name}")

    backup_size = args.backup.stat().st_size
    backup_checksum = sha256_file(args.backup)
    admin_user = args.admin_user
    admin_password = args.admin_password_file.read_text(encoding="utf-8").rstrip("\r\n")
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
        restore_started = time.monotonic()
        runner(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "0",
                "--entrypoint",
                "tar",
                "--mount",
                f"type=volume,source={volume},target=/target",
                "--mount",
                f"type=bind,source={args.backup.resolve()},target=/backup/archive,readonly",
                args.image,
                "-xf",
                "/backup/archive",
                "-C",
                "/target",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        runner(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "0",
                "--entrypoint",
                "chown",
                "--mount",
                f"type=volume,source={volume},target=/target",
                args.image,
                "-R",
                "472:0",
                "/target",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        restore_seconds = time.monotonic() - restore_started
        if sha256_file(args.backup) != backup_checksum:
            raise RuntimeError("backup changed while the restore was running")

        anonymous_enabled = args.anonymous_role != "disabled"
        run_command = [
            "docker",
            "run",
            "--detach",
            "--name",
            container,
            "--publish",
            "127.0.0.1::3000",
            "--env",
            f"GF_AUTH_ANONYMOUS_ENABLED={str(anonymous_enabled).lower()}",
            "--env",
            f"GF_AUTH_ANONYMOUS_ORG_ROLE={args.anonymous_role if anonymous_enabled else 'Viewer'}",
            "--env",
            "GF_AUTH_DISABLE_LOGIN_FORM=true",
            "--env",
            "GF_ANALYTICS_REPORTING_ENABLED=false",
            "--env",
            "GF_ANALYTICS_CHECK_FOR_UPDATES=false",
            "--mount",
            f"type=volume,source={volume},target=/var/lib/grafana",
        ]
        if args.provisioning_dir is not None:
            run_command.extend(
                [
                    "--mount",
                    "type=bind,"
                    f"source={args.provisioning_dir.resolve()},"
                    "target=/etc/grafana/provisioning,readonly",
                    "--mount",
                    "type=bind,"
                    f"source={args.dashboards_dir.resolve()},"
                    "target=/var/lib/grafana/dashboards,readonly",
                ]
            )
        run_command.append(args.image)
        runner(
            run_command,
            check=True,
            capture_output=True,
            text=True,
        )
        port_result = runner(
            ["docker", "port", container, "3000/tcp"],
            check=True,
            capture_output=True,
            text=True,
        )
        port = int(port_result.stdout.strip().rsplit(":", 1)[1])
        origin = f"http://127.0.0.1:{port}"
        health = wait_for_grafana(origin, args.expected_version, getter)
        credentials = (admin_user, admin_password)

        dashboards: dict[str, dict[str, bool]] = {}
        for uid, expected_title in args.expect_dashboard:
            payload = get_json(
                origin, f"/api/dashboards/uid/{quote(uid, safe='')}", getter, credentials
            )
            title_met = payload.get("dashboard", {}).get("title") == expected_title
            if not title_met:
                raise RuntimeError(f"dashboard title mismatch for UID {uid}")
            dashboards[uid] = {
                "present": True,
                "title_met": True,
                "provisioned": bool(payload.get("meta", {}).get("provisioned", False)),
            }
        if not any(not result["provisioned"] for result in dashboards.values()):
            raise RuntimeError("at least one expected non-provisioned dashboard is required")

        folders: dict[str, dict[str, bool]] = {}
        for uid, expected_title in args.expect_folder:
            payload = get_json(origin, f"/api/folders/{quote(uid, safe='')}", getter, credentials)
            title_met = payload.get("title") == expected_title
            if not title_met:
                raise RuntimeError(f"folder title mismatch for UID {uid}")
            folders[uid] = {"present": True, "title_met": True}

        datasources: dict[str, dict[str, bool]] = {}
        for uid, expected_type, expected_url in args.expect_datasource:
            payload = get_json(
                origin, f"/api/datasources/uid/{quote(uid, safe='')}", getter, credentials
            )
            type_met = payload.get("type") == expected_type
            url_met = payload.get("url") == expected_url
            if not type_met or not url_met:
                raise RuntimeError(f"datasource mismatch for UID {uid}")
            datasources[uid] = {"present": True, "type_met": True, "url_met": True}

        access_policy = validate_access_policy(
            origin, args.anonymous_role, args.expect_dashboard[0][0], getter, credentials
        )
        database_result = runner(
            ["docker", "exec", container, "stat", "-c", "%s", "/var/lib/grafana/grafana.db"],
            check=True,
            capture_output=True,
            text=True,
        )
        migrated_database_bytes = int(database_result.stdout.strip())
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
                **archive,
            },
            "restore": {
                "image": args.image,
                "grafana_version": health["version"],
                "duration_seconds": round(restore_seconds, 3),
                "recovery_duration_seconds": round(recovery_seconds, 3),
                "migrated_database_bytes": migrated_database_bytes,
                "rto_met": recovery_seconds <= args.rto_seconds,
                "observed_rpo_seconds": round(args.observed_rpo_seconds, 3),
                "rpo_met": args.observed_rpo_seconds <= args.rpo_seconds,
            },
            "integrity": {
                "database": health["database"],
                "dashboards": dashboards,
                "folders": folders,
                "datasources": datasources,
                "access_policy": access_policy,
                "provisioning_mounted": args.provisioning_dir is not None,
            },
            "target_preserved": args.preserve_target,
        }
    finally:
        if not args.preserve_target or not succeeded:
            cleanup(container, volume, runner)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="pinned Grafana 13 image")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--backup", type=Path, required=True, help="stopped-volume tar archive")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-password-file", type=Path, required=True)
    parser.add_argument("--provisioning-dir", type=Path)
    parser.add_argument("--dashboards-dir", type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--write-freeze-at", type=parse_utc_timestamp, required=True)
    parser.add_argument("--backup-created-at", type=parse_utc_timestamp, required=True)
    parser.add_argument("--backup-duration-seconds", type=float, required=True)
    parser.add_argument("--rto-seconds", type=float, required=True)
    parser.add_argument("--rpo-seconds", type=float, required=True)
    parser.add_argument("--observed-rpo-seconds", type=float, required=True)
    parser.add_argument(
        "--expect-dashboard", action="append", type=parse_named_expectation, default=[]
    )
    parser.add_argument(
        "--expect-folder", action="append", type=parse_named_expectation, default=[]
    )
    parser.add_argument(
        "--expect-datasource", action="append", type=parse_datasource_expectation, default=[]
    )
    parser.add_argument(
        "--anonymous-role", choices=("disabled", "Viewer", "Editor"), default="disabled"
    )
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
