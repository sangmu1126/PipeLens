"""Install PipeLens for a prerelease Python without weakening production metadata."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

PROJECT_FILE = Path("pyproject.toml")
PSYCOPG_BINARY_PREFIX = "psycopg[binary]"
PSYCOPG_PREVIEW_PREFIX = "psycopg"


def preview_requirements(project: dict[str, Any]) -> list[str]:
    runtime = project.get("project", {}).get("dependencies")
    development = project.get("project", {}).get("optional-dependencies", {}).get("dev")
    if not isinstance(runtime, list) or not all(isinstance(item, str) for item in runtime):
        raise ValueError("project.dependencies must be a list of strings")
    if not isinstance(development, list) or not all(
        isinstance(item, str) for item in development
    ):
        raise ValueError("project.optional-dependencies.dev must be a list of strings")

    replacements = 0
    requirements: list[str] = []
    for requirement in [*runtime, *development]:
        if requirement.startswith(PSYCOPG_BINARY_PREFIX):
            requirement = requirement.replace(
                PSYCOPG_BINARY_PREFIX, PSYCOPG_PREVIEW_PREFIX, 1
            )
            replacements += 1
        requirements.append(requirement)
    if replacements != 1:
        raise ValueError(
            "expected exactly one psycopg[binary] production dependency, "
            f"found {replacements}"
        )
    return requirements


def load_project(path: Path = PROJECT_FILE) -> dict[str, Any]:
    with path.open("rb") as project_file:
        return tomllib.load(project_file)


def install(requirements: list[str]) -> None:
    print(
        "Python preview only: replacing psycopg[binary] with psycopg's "
        "pure-Python/libpq implementation."
    )
    subprocess.run(
        [sys.executable, "-m", "pip", "install", *requirements],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--ignore-requires-python",
            "--no-deps",
            "--editable",
            ".",
        ],
        check=True,
    )


def main() -> int:
    try:
        requirements = preview_requirements(load_project())
        install(requirements)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Python preview dependency installation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
