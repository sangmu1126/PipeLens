from pathlib import Path

from ops.ci.verify_dockerfile_pinning import find_dockerfiles, find_mutable_base_images


def test_pinning_accepts_digests_scratch_and_local_stages(tmp_path: Path) -> None:
    digest = "a" * 64
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        f"FROM --platform=linux/amd64 python:3.14-slim@sha256:{digest} AS build\n"
        "FROM build AS packaged\n"
        "FROM scratch\n",
        encoding="utf-8",
    )

    assert find_mutable_base_images([dockerfile]) == []


def test_pinning_reports_mutable_references_with_locations(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile.worker"
    dockerfile.write_text(
        "FROM python:3.14-slim AS build\nFROM ${RUNTIME_IMAGE}\n",
        encoding="utf-8",
    )

    assert find_mutable_base_images([dockerfile]) == [
        f"{dockerfile}:1: python:3.14-slim",
        f"{dockerfile}:2: ${{RUNTIME_IMAGE}}",
    ]


def test_discovery_excludes_generated_dependency_directories(tmp_path: Path) -> None:
    expected = tmp_path / "frontend" / "Dockerfile"
    expected.parent.mkdir()
    expected.touch()
    ignored = tmp_path / "node_modules" / "package" / "Dockerfile.build"
    ignored.parent.mkdir(parents=True)
    ignored.touch()

    assert find_dockerfiles(tmp_path) == [expected]
