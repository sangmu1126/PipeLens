"""Audit the public GHCR inventory against PipeLens retention policy."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Final

SEMVER_TAG: Final = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
DIGEST_TAG: Final = re.compile(r"^sha256-[0-9a-f]{64}$")
NAME: Final = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
MANIFEST_TYPES: Final = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


class AuditError(RuntimeError):
    """Raised when registry state violates the retention policy."""


@dataclass(frozen=True)
class PackageInventory:
    name: str
    tags: frozenset[str]
    release_digests: dict[str, str]


def digest_tag(digest: str) -> str:
    if not DIGEST.fullmatch(digest):
        raise AuditError(f"invalid manifest digest: {digest!r}")
    return digest.replace(":", "-", 1)


def validate_inventories(inventories: list[PackageInventory]) -> list[str]:
    """Validate paired release and attestation tags, returning sorted releases."""
    if len(inventories) < 2:
        raise AuditError("at least two package inventories are required")

    errors: list[str] = []
    release_sets: list[set[str]] = []
    for inventory in inventories:
        release_tags = {tag for tag in inventory.tags if SEMVER_TAG.fullmatch(tag)}
        digest_tags = {tag for tag in inventory.tags if DIGEST_TAG.fullmatch(tag)}
        unexpected = inventory.tags - release_tags - digest_tags
        if unexpected:
            errors.append(f"{inventory.name}: unexpected tags: {sorted(unexpected)}")
        if not release_tags:
            errors.append(f"{inventory.name}: no SemVer release tags")
        if set(inventory.release_digests) != release_tags:
            errors.append(f"{inventory.name}: digest inventory does not match release tags")

        expected_digest_tags: set[str] = set()
        for tag, digest in inventory.release_digests.items():
            try:
                expected_digest_tags.add(digest_tag(digest))
            except AuditError as error:
                errors.append(f"{inventory.name}:{tag}: {error}")
        missing = expected_digest_tags - digest_tags
        orphaned = digest_tags - expected_digest_tags
        if missing:
            errors.append(f"{inventory.name}: missing attestation tags: {sorted(missing)}")
        if orphaned:
            errors.append(f"{inventory.name}: orphaned attestation tags: {sorted(orphaned)}")
        release_sets.append(release_tags)

    expected_releases = release_sets[0]
    for inventory, releases in zip(inventories[1:], release_sets[1:], strict=True):
        if releases != expected_releases:
            errors.append(
                f"{inventory.name}: release tags differ from {inventories[0].name}: "
                f"{sorted(releases)} != {sorted(expected_releases)}"
            )

    if errors:
        raise AuditError("\n".join(errors))
    return sorted(expected_releases)


class RegistryClient:
    def __init__(self, namespace: str) -> None:
        if not NAME.fullmatch(namespace):
            raise AuditError(f"invalid GHCR namespace: {namespace!r}")
        self.namespace = namespace.lower()

    @staticmethod
    def _read_json(request: urllib.request.Request) -> dict[str, object]:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                return json.load(response)
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
            raise AuditError(f"registry request failed: {request.full_url}: {error}") from error

    def _token(self, repository: str) -> str:
        query = urllib.parse.urlencode({"scope": f"repository:{repository}:pull"})
        request = urllib.request.Request(
            f"https://ghcr.io/token?{query}", headers={"User-Agent": "PipeLens-GHCR-Audit/1"}
        )
        payload = self._read_json(request)
        token = payload.get("token") or payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise AuditError(f"GHCR did not issue a pull token for {repository}")
        return token

    @staticmethod
    def _request(url: str, token: str, *, method: str = "GET") -> urllib.request.Request:
        return urllib.request.Request(
            url,
            method=method,
            headers={
                "Accept": MANIFEST_TYPES,
                "Authorization": f"Bearer {token}",
                "User-Agent": "PipeLens-GHCR-Audit/1",
            },
        )

    def inventory(self, package: str) -> PackageInventory:
        if not NAME.fullmatch(package):
            raise AuditError(f"invalid GHCR package name: {package!r}")
        repository = f"{self.namespace}/{package.lower()}"
        token = self._token(repository)
        tags_url = f"https://ghcr.io/v2/{repository}/tags/list?n=1000"
        payload = self._read_json(self._request(tags_url, token))
        tags_value = payload.get("tags")
        if not isinstance(tags_value, list) or not all(isinstance(tag, str) for tag in tags_value):
            raise AuditError(f"{repository}: invalid tags response")
        tags = frozenset(tags_value)

        release_digests: dict[str, str] = {}
        for tag in sorted(tag for tag in tags if SEMVER_TAG.fullmatch(tag)):
            quoted_tag = urllib.parse.quote(tag, safe="")
            manifest_url = f"https://ghcr.io/v2/{repository}/manifests/{quoted_tag}"
            request = self._request(manifest_url, token, method="HEAD")
            try:
                with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                    digest = response.headers.get("Docker-Content-Digest", "")
            except (OSError, urllib.error.HTTPError) as error:
                raise AuditError(f"manifest request failed: {repository}:{tag}: {error}") from error
            release_digests[tag] = digest

        return PackageInventory(repository, tags, release_digests)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True, help="GHCR account namespace")
    parser.add_argument(
        "--package",
        action="append",
        dest="packages",
        help="package to audit; repeat for each package",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packages = args.packages or ["pipelens-api", "pipelens-dashboard"]
    try:
        client = RegistryClient(args.namespace)
        inventories = [client.inventory(package) for package in packages]
        releases = validate_inventories(inventories)
    except AuditError as error:
        print(f"GHCR retention audit failed:\n{error}", file=sys.stderr)
        return 1

    for inventory in inventories:
        print(f"{inventory.name}: {len(inventory.tags)} tags, {len(releases)} releases")
    print(f"GHCR retention audit passed: {', '.join(releases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
