from __future__ import annotations

import io
import urllib.request

import pytest

from ops.ghcr.audit_retention import (
    AuditError,
    PackageInventory,
    RegistryClient,
    validate_inventories,
)

DIGEST = "sha256:" + "a" * 64
DIGEST_TAG = "sha256-" + "a" * 64


def inventory(name: str, tags: set[str], releases: dict[str, str]) -> PackageInventory:
    return PackageInventory(name=name, tags=frozenset(tags), release_digests=releases)


def test_matching_release_and_attestation_inventory_passes() -> None:
    tags = {"v0.1.0", DIGEST_TAG}
    inventories = [
        inventory("owner/pipelens-api", tags, {"v0.1.0": DIGEST}),
        inventory("owner/pipelens-dashboard", tags, {"v0.1.0": DIGEST}),
    ]

    assert validate_inventories(inventories) == ["v0.1.0"]


@pytest.mark.parametrize(
    ("tags", "releases", "message"),
    [
        ({"latest", "v0.1.0", DIGEST_TAG}, {"v0.1.0": DIGEST}, "unexpected tags"),
        ({"v0.1.0"}, {"v0.1.0": DIGEST}, "missing attestation tags"),
        ({DIGEST_TAG}, {}, "no SemVer release tags"),
        ({"v0.1.0", DIGEST_TAG}, {"v0.1.0": "bad"}, "invalid manifest digest"),
    ],
)
def test_invalid_package_inventory_fails(
    tags: set[str], releases: dict[str, str], message: str
) -> None:
    inventories = [
        inventory("owner/pipelens-api", tags, releases),
        inventory("owner/pipelens-dashboard", tags, releases),
    ]

    with pytest.raises(AuditError, match=message):
        validate_inventories(inventories)


def test_package_release_sets_must_match() -> None:
    inventories = [
        inventory("owner/pipelens-api", {"v0.1.0", DIGEST_TAG}, {"v0.1.0": DIGEST}),
        inventory("owner/pipelens-dashboard", {"v0.2.0", DIGEST_TAG}, {"v0.2.0": DIGEST}),
    ]

    with pytest.raises(AuditError, match="release tags differ"):
        validate_inventories(inventories)


def test_registry_client_rejects_non_object_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(b"[]"),
    )

    with pytest.raises(AuditError, match="non-object"):
        RegistryClient._read_json(urllib.request.Request("https://ghcr.io/v2/test/tags/list"))
