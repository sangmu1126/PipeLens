"""Reject mutable external GitHub Action references in workflow files."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW_DIRECTORY = Path(".github/workflows")
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*([^\s#]+)")
PINNED_ACTION = re.compile(r"^[^/@\s]+/[^/@\s]+(?:/[^@\s]+)?@[0-9a-f]{40}$")


def find_mutable_actions(workflow_directory: Path) -> list[str]:
    """Return workflow locations containing mutable external action references."""
    mutable: list[str] = []
    workflow_paths = sorted(workflow_directory.glob("*.yml")) + sorted(
        workflow_directory.glob("*.yaml")
    )
    for path in workflow_paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = USES_LINE.match(line)
            if match is None:
                continue
            reference = match.group(1)
            if reference.startswith(("./", "docker://")):
                continue
            if not PINNED_ACTION.fullmatch(reference):
                mutable.append(f"{path}:{line_number}: {reference}")
    return mutable


def main() -> int:
    mutable = find_mutable_actions(WORKFLOW_DIRECTORY)
    if mutable:
        details = "\n".join(f"- {item}" for item in mutable)
        raise SystemExit(f"external GitHub Actions must use full commit SHAs:\n{details}")
    print("all external GitHub Actions are pinned to full commit SHAs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
