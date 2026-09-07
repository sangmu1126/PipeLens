from __future__ import annotations

import pytest

from ops.grafana.image_version import parse_grafana_version


def test_parse_grafana_version_from_pinned_image() -> None:
    image = "grafana/grafana:13.2.1@sha256:" + "a" * 64

    assert parse_grafana_version(image) == "13.2.1"


@pytest.mark.parametrize(
    "image",
    [
        "grafana/grafana:13.2.1",
        "grafana/grafana:latest@sha256:" + "a" * 64,
        "other/grafana:13.2.1@sha256:" + "a" * 64,
        "grafana/grafana:13.2.1@sha256:not-a-digest",
    ],
)
def test_parse_grafana_version_rejects_unpinned_or_unversioned_image(
    image: str,
) -> None:
    with pytest.raises(ValueError, match="Grafana image must be"):
        parse_grafana_version(image)
