from pathlib import Path

import pytest

from ops.ci.install_python_preview import load_project, preview_requirements


def test_repository_preview_requirements_replace_only_binary_extra() -> None:
    requirements = preview_requirements(load_project())

    assert "psycopg>=3.3.5,<4" in requirements
    assert all(not requirement.startswith("psycopg[binary]") for requirement in requirements)
    assert "pytest>=9.1.1,<10" in requirements


def test_preview_requirements_preserve_markers_and_other_extras() -> None:
    project = {
        "project": {
            "dependencies": [
                'example[feature]>=1; python_version >= "3.15"',
                "psycopg[binary]>=3.3,<4",
            ],
            "optional-dependencies": {"dev": ["pytest>=9"]},
        }
    }

    assert preview_requirements(project) == [
        'example[feature]>=1; python_version >= "3.15"',
        "psycopg>=3.3,<4",
        "pytest>=9",
    ]


@pytest.mark.parametrize(
    "dependencies",
    [
        ["psycopg>=3.3,<4"],
        ["psycopg[binary]>=3.3,<4", "psycopg[binary]>=3.3,<4"],
    ],
)
def test_preview_requirements_require_one_reviewed_replacement(
    dependencies: list[str],
) -> None:
    project = {
        "project": {
            "dependencies": dependencies,
            "optional-dependencies": {"dev": ["pytest>=9"]},
        }
    }

    with pytest.raises(ValueError, match="exactly one"):
        preview_requirements(project)


def test_load_project_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_project(tmp_path / "missing.toml")
