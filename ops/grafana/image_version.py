from __future__ import annotations

import argparse
import re

GRAFANA_IMAGE_PATTERN = re.compile(
    r"^grafana/grafana:(?P<version>[0-9]+\.[0-9]+\.[0-9]+)@sha256:[0-9a-f]{64}$"
)


def parse_grafana_version(image: str) -> str:
    match = GRAFANA_IMAGE_PATTERN.fullmatch(image)
    if match is None:
        raise ValueError(
            "Grafana image must be grafana/grafana:MAJOR.MINOR.PATCH@sha256:DIGEST"
        )
    return match.group("version")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print the semantic version from a digest-pinned Grafana image."
    )
    parser.add_argument("image")
    args = parser.parse_args()

    try:
        version = parse_grafana_version(args.image)
    except ValueError as error:
        parser.error(str(error))
    print(version)


if __name__ == "__main__":
    main()
