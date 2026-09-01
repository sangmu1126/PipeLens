from __future__ import annotations

import argparse
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from ops.grafana.verify_restore import (
    inspect_archive,
    parse_args,
    parse_datasource_expectation,
    parse_named_expectation,
    run_drill,
    validate_access_policy,
    validate_args,
)

PINNED_IMAGE = "grafana/grafana:13.2.0@sha256:" + "a" * 64


def make_backup(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def base_args(tmp_path: Path) -> argparse.Namespace:
    backup = tmp_path / "grafana.tgz"
    password = tmp_path / "admin-password"
    make_backup(backup, {"grafana.db": b"sqlite-data", "png/file.png": b"image"})
    password.write_text("admin-secret", encoding="utf-8")
    return parse_args(
        [
            "--image",
            PINNED_IMAGE,
            "--expected-version",
            "13.2.0",
            "--backup",
            str(backup),
            "--admin-user",
            "fixture-admin",
            "--admin-password-file",
            str(password),
            "--provisioning-dir",
            str(tmp_path),
            "--dashboards-dir",
            str(tmp_path),
            "--source-revision",
            "release-2026-09-01",
            "--write-freeze-at",
            "2025-09-01T14:00:00Z",
            "--backup-created-at",
            "2025-09-01T14:00:05Z",
            "--backup-duration-seconds",
            "5",
            "--rto-seconds",
            "300",
            "--rpo-seconds",
            "60",
            "--observed-rpo-seconds",
            "30",
            "--expect-dashboard",
            "operations=Operations",
            "--expect-folder",
            "pipelens=PipeLens",
            "--expect-datasource",
            "prometheus=prometheus,http://prometheus:9090",
            "--anonymous-role",
            "Viewer",
            "--run-id",
            "production-test",
            "--output",
            str(tmp_path / "evidence.json"),
        ]
    )


def test_parse_expectations() -> None:
    assert parse_named_expectation("operations=Operations") == ("operations", "Operations")
    assert parse_datasource_expectation("prometheus=prometheus,http://prometheus:9090") == (
        "prometheus",
        "prometheus",
        "http://prometheus:9090",
    )


@pytest.mark.parametrize("value", ["missing", "bad uid=Title", "uid="])
def test_parse_named_expectation_rejects_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_named_expectation(value)


@pytest.mark.parametrize("value", ["missing", "uid=type", "uid=,url", "uid=type,"])
def test_parse_datasource_expectation_rejects_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_datasource_expectation(value)


def test_inspect_archive_records_sizes(tmp_path: Path) -> None:
    backup = tmp_path / "grafana.tgz"
    make_backup(backup, {"./grafana.db": b"database", "plugins/plugin.txt": b"plugin"})
    assert inspect_archive(backup) == {
        "member_count": 2,
        "uncompressed_bytes": 14,
        "database_bytes": 8,
    }


def test_inspect_archive_rejects_path_traversal_and_links(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.tar"
    make_backup(traversal, {"grafana.db": b"database", "../escape": b"bad"})
    with pytest.raises(ValueError, match="unsafe archive member"):
        inspect_archive(traversal)

    link_backup = tmp_path / "link.tar"
    with tarfile.open(link_backup, "w") as archive:
        database = tarfile.TarInfo("grafana.db")
        database.size = 8
        archive.addfile(database, io.BytesIO(b"database"))
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    with pytest.raises(ValueError, match="unsafe archive member"):
        inspect_archive(link_backup)


def test_inspect_archive_requires_root_database(tmp_path: Path) -> None:
    backup = tmp_path / "nested.tar"
    make_backup(backup, {"nested/grafana.db": b"database"})
    with pytest.raises(ValueError, match="root grafana.db"):
        inspect_archive(backup)


def test_validate_args_requires_all_integrity_expectations(tmp_path: Path) -> None:
    args = base_args(tmp_path)
    args.expect_folder = []
    with pytest.raises(ValueError, match="all required"):
        validate_args(args)


def test_validate_args_rejects_mutable_image(tmp_path: Path) -> None:
    args = base_args(tmp_path)
    args.image = "grafana/grafana:13.2.0"
    with pytest.raises(ValueError, match="image"):
        validate_args(args)


def test_validate_disabled_access_policy() -> None:
    def fake_getter(url: str, credentials: tuple[str, str] | None) -> tuple[int, bytes, str]:
        if url.endswith("/api/admin/settings") and credentials is not None:
            payload = {"auth.anonymous": {"enabled": "false", "org_role": "Viewer"}}
            return 200, json.dumps(payload).encode(), "application/json"
        return 401, b"{}", "application/json"

    assert validate_access_policy(
        "http://127.0.0.1:3000",
        "disabled",
        "operations",
        fake_getter,
        ("admin", "secret"),
    ) == {
        "anonymous_enabled": False,
        "anonymous_role": "disabled",
        "anonymous_dashboard_allowed": False,
        "anonymous_admin_denied": True,
    }


def test_run_drill_emits_redacted_evidence_and_cleans_target(tmp_path: Path) -> None:
    args = base_args(tmp_path)
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
        elif command[1:3] == ["volume", "rm"]:
            volumes.remove(command[3])
        elif command[1:3] == ["port", "pipelens-grafana-restore-production-test"]:
            stdout = "127.0.0.1:53123\n"
        elif command[1:3] == ["exec", "pipelens-grafana-restore-production-test"]:
            stdout = "123456\n"
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")

    def fake_getter(url: str, credentials: tuple[str, str] | None) -> tuple[int, bytes, str]:
        if url.endswith("/api/health"):
            payload = {"database": "ok", "version": "13.2.0"}
        elif url.endswith("/api/dashboards/uid/operations"):
            if credentials is None:
                return 200, b"{}", "application/json"
            payload = {"dashboard": {"title": "Operations"}, "meta": {"provisioned": False}}
        elif url.endswith("/api/folders/pipelens"):
            payload = {"title": "PipeLens"}
        elif url.endswith("/api/datasources/uid/prometheus"):
            payload = {"type": "prometheus", "url": "http://prometheus:9090"}
        elif url.endswith("/api/admin/settings") and credentials is None:
            return 401, b"{}", "application/json"
        elif url.endswith("/api/admin/settings"):
            payload = {"auth.anonymous": {"enabled": "true", "org_role": "Viewer"}}
        else:
            raise AssertionError(url)
        return 200, json.dumps(payload).encode(), "application/json"

    evidence = run_drill(args, fake_runner, fake_getter)

    assert evidence["restore"]["grafana_version"] == "13.2.0"  # type: ignore[index]
    assert evidence["restore"]["rto_met"] is True  # type: ignore[index]
    assert evidence["restore"]["rpo_met"] is True  # type: ignore[index]
    assert evidence["integrity"]["access_policy"]["anonymous_admin_denied"] is True  # type: ignore[index]
    assert str(args.backup) not in str(evidence)
    assert "admin-secret" not in str(evidence)
    assert not containers
    assert not volumes
