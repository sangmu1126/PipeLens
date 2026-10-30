import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED_REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==\S+ \\$")


def _requirement_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_runtime_manifest_matches_project_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert _requirement_lines(ROOT / "requirements.in") == project["project"]["dependencies"]


def test_runtime_lock_is_hashed_pip_compile_output() -> None:
    lock = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    entries = [line for line in lock.splitlines() if PINNED_REQUIREMENT.match(line)]
    hashes = [line for line in lock.splitlines() if line.strip().startswith("--hash=sha256:")]

    assert "--output-file=requirements.txt" in lock
    assert "--strip-extras requirements.in" in lock
    assert entries
    assert len(hashes) >= len(entries)


def test_runtime_lock_pins_every_direct_dependency() -> None:
    lock = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pinned = {
        _normalize(match.group(1))
        for line in lock.splitlines()
        if (match := PINNED_REQUIREMENT.match(line))
    }
    direct = {
        _normalize(re.split(r"[\[<>=!~;\s]", requirement, maxsplit=1)[0])
        for requirement in _requirement_lines(ROOT / "requirements.in")
    }

    assert direct <= pinned


def test_images_install_only_from_the_hashed_lock() -> None:
    for dockerfile in (ROOT / "Dockerfile", ROOT / "ops" / "worker" / "Dockerfile"):
        content = dockerfile.read_text(encoding="utf-8")

        assert "--require-hashes" in content
        assert "-r requirements.txt" in content
        assert "pip install --no-cache-dir ." not in content
