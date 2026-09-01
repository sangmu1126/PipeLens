"""Reject mutable external base image references in Dockerfiles."""

from __future__ import annotations

import re
from pathlib import Path

IGNORED_DIRECTORIES = {".git", ".venv", "node_modules"}
FROM_LINE = re.compile(
    r"^\s*FROM(?:\s+--platform=\S+)?\s+(?P<image>\S+)"
    r"(?:\s+AS\s+(?P<alias>\S+))?\s*$",
    re.IGNORECASE,
)
PINNED_IMAGE = re.compile(r"^.+:[^/@\s]+@sha256:[0-9a-f]{64}$")


def find_dockerfiles(root: Path) -> list[Path]:
    """Return repository Dockerfiles while excluding generated dependency trees."""
    return sorted(
        path
        for path in root.rglob("Dockerfile*")
        if path.is_file() and not IGNORED_DIRECTORIES.intersection(path.parts)
    )


def find_mutable_base_images(dockerfiles: list[Path]) -> list[str]:
    """Return Dockerfile locations containing mutable external FROM references."""
    mutable: list[str] = []
    for path in dockerfiles:
        local_stages: set[str] = set()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = FROM_LINE.match(line)
            if match is None:
                continue
            image = match.group("image")
            external_image = image != "scratch" and image not in local_stages
            if external_image and not PINNED_IMAGE.fullmatch(image):
                mutable.append(f"{path}:{line_number}: {image}")
            alias = match.group("alias")
            if alias:
                local_stages.add(alias)
    return mutable


def main() -> int:
    dockerfiles = find_dockerfiles(Path("."))
    if not dockerfiles:
        raise SystemExit("repository contains no Dockerfiles")
    mutable = find_mutable_base_images(dockerfiles)
    if mutable:
        details = "\n".join(f"- {item}" for item in mutable)
        raise SystemExit(f"external Dockerfile base images must use tag@sha256 digest:\n{details}")
    print(f"all external base images are pinned in {len(dockerfiles)} Dockerfiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
