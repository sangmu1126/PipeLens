"""Audit live GitHub repository settings against the documented PipeLens policy."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Final

API_VERSION: Final = "2022-11-28"
REPOSITORY_NAME: Final = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
DESCRIPTION: Final = "Evidence-first diagnostics for failed GitHub Actions runs"
TOPICS: Final = frozenset(
    {
        "ci-cd",
        "developer-tools",
        "devops",
        "fastapi",
        "github-actions",
        "observability",
        "python",
        "react",
        "typescript",
    }
)
GITHUB_ACTIONS_APP_ID: Final = 15368
REQUIRED_CHECKS: Final = frozenset(
    {
        "backend",
        "Python 3.14 compatibility",
        "dashboard",
        "Build container (api)",
        "Build container (dashboard)",
        "Analyze (python)",
        "Analyze (javascript-typescript)",
        "Repository secret scan",
        "Dependency review",
    }
)


class AuditError(RuntimeError):
    """Raised when GitHub state cannot be audited safely."""


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    expected: object
    actual: object


def _nested(payload: dict[str, object], *path: str) -> object:
    value: object = payload
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def audit_snapshot(
    repository: dict[str, object],
    protection: dict[str, object],
    private_reporting: dict[str, object],
    milestone: dict[str, object],
    release: dict[str, object],
) -> dict[str, object]:
    """Return a redacted, machine-readable governance report."""
    checks: list[Check] = []

    def check(name: str, actual: object, expected: object) -> None:
        checks.append(Check(name=name, passed=actual == expected, expected=expected, actual=actual))

    check("repository.visibility", repository.get("visibility"), "public")
    check("repository.default_branch", repository.get("default_branch"), "main")
    check("repository.description", repository.get("description"), DESCRIPTION)
    check("repository.homepage", repository.get("homepage"), None)
    topics = repository.get("topics")
    normalized_topics = sorted(topics) if isinstance(topics, list) else topics
    check("repository.topics", normalized_topics, sorted(TOPICS))
    check("merge.squash_enabled", repository.get("allow_squash_merge"), True)
    check("merge.rebase_enabled", repository.get("allow_rebase_merge"), True)
    check("merge.commit_disabled", repository.get("allow_merge_commit"), False)
    check("merge.delete_branch", repository.get("delete_branch_on_merge"), True)

    security = repository.get("security_and_analysis")
    for feature in (
        "secret_scanning",
        "secret_scanning_push_protection",
        "dependabot_security_updates",
    ):
        security_payload = security if isinstance(security, dict) else {}
        check(f"security.{feature}", _nested(security_payload, feature, "status"), "enabled")
    check("security.private_vulnerability_reporting", private_reporting.get("enabled"), True)

    status_checks = protection.get("required_status_checks")
    status_checks = status_checks if isinstance(status_checks, dict) else {}
    check("protection.strict", status_checks.get("strict"), True)
    raw_checks = status_checks.get("checks")
    actual_checks: dict[str, object] = {}
    if isinstance(raw_checks, list):
        for item in raw_checks:
            if isinstance(item, dict) and isinstance(item.get("context"), str):
                actual_checks[item["context"]] = item.get("app_id")
    check(
        "protection.required_checks",
        actual_checks,
        {context: GITHUB_ACTIONS_APP_ID for context in sorted(REQUIRED_CHECKS)},
    )
    reviews = protection.get("required_pull_request_reviews")
    reviews = reviews if isinstance(reviews, dict) else {}
    check("protection.pull_request_required", bool(reviews), True)
    check("protection.required_approvals", reviews.get("required_approving_review_count"), 0)
    enabled_protections = (
        "enforce_admins",
        "required_linear_history",
        "required_conversation_resolution",
    )
    for setting in enabled_protections:
        check(f"protection.{setting}", _nested(protection, setting, "enabled"), True)
    for setting in ("allow_force_pushes", "allow_deletions"):
        check(f"protection.{setting}", _nested(protection, setting, "enabled"), False)

    passed = all(item.passed for item in checks)
    return {
        "schema_version": 1,
        "repository": repository.get("full_name"),
        "checked_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "checks": [asdict(item) for item in checks],
        "observations": {
            "open_issues": repository.get("open_issues_count"),
            "milestone": milestone.get("title"),
            "milestone_open": milestone.get("open_issues"),
            "milestone_closed": milestone.get("closed_issues"),
            "latest_release": release.get("tag_name"),
            "latest_release_immutable": release.get("immutable"),
        },
    }


class GitHubClient:
    def __init__(self, repository: str, token: str) -> None:
        if not REPOSITORY_NAME.fullmatch(repository):
            raise AuditError(f"invalid repository name: {repository!r}")
        if not token:
            raise AuditError("GITHUB_TOKEN or GH_TOKEN is required")
        self.repository = repository
        self.token = token

    def get(self, path: str) -> dict[str, object]:
        request = urllib.request.Request(
            f"https://api.github.com{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "PipeLens-Governance-Audit/1",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                payload = json.load(response)
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
            raise AuditError(f"GitHub request failed: {path}: {error}") from error
        if not isinstance(payload, dict):
            raise AuditError(f"GitHub returned a non-object response: {path}")
        return payload

    def snapshot(self, milestone_number: int) -> dict[str, object]:
        base = f"/repos/{self.repository}"
        return audit_snapshot(
            self.get(base),
            self.get(f"{base}/branches/main/protection"),
            self.get(f"{base}/private-vulnerability-reporting"),
            self.get(f"{base}/milestones/{milestone_number}"),
            self.get(f"{base}/releases/latest"),
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="sangmu1126/PipeLens")
    parser.add_argument("--milestone", type=int, default=1)
    parser.add_argument("--output", help="optional path for the JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    try:
        report = GitHubClient(args.repository, token).snapshot(args.milestone)
    except AuditError as error:
        print(f"repository governance audit failed: {error}", file=sys.stderr)
        return 2

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            output.write(rendered)
    else:
        print(rendered, end="")

    if report.get("passed") is not True:
        raw_checks = report.get("checks")
        failed = (
            [
                str(item.get("name"))
                for item in raw_checks
                if isinstance(item, dict) and item.get("passed") is not True
            ]
            if isinstance(raw_checks, list)
            else ["invalid report checks"]
        )
        print(f"repository governance drift: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
