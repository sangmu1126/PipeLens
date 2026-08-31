"""Export or verify the committed PipeLens OpenAPI contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipelens.config import Settings
from pipelens.main import create_app

DEFAULT_OUTPUT = Path("docs/openapi.json")


def render_openapi() -> str:
    app = create_app(
        Settings(
            auth_required=False,
            database_path=":memory:",
        )
    )
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rendered = render_openapi()
    if args.write:
        args.output.write_text(rendered, encoding="utf-8")
        return 0
    if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
        raise SystemExit(
            f"OpenAPI contract drifted; run {__file__} --write and review the diff"
        )
    print("committed OpenAPI contract matches the application")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
