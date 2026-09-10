from __future__ import annotations

from typing import Any, cast

import pytest

from ops.governance.audit_repository import (
    DESCRIPTION,
    GITHUB_ACTIONS_APP_ID,
    REQUIRED_CHECKS,
    TOPICS,
    AuditError,
    GitHubClient,
    audit_snapshot,
)


def valid_snapshot() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    repository: dict[str, object] = {
        "full_name": "sangmu1126/PipeLens",
        "visibility": "public",
        "default_branch": "main",
        "description": DESCRIPTION,
        "homepage": None,
        "topics": sorted(TOPICS),
        "allow_squash_merge": True,
        "allow_rebase_merge": True,
        "allow_merge_commit": False,
        "delete_branch_on_merge": True,
        "open_issues_count": 4,
        "security_and_analysis": {
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
            "dependabot_security_updates": {"status": "enabled"},
        },
    }
    protection: dict[str, object] = {
        "required_status_checks": {
            "strict": True,
            "checks": [
                {"context": context, "app_id": GITHUB_ACTIONS_APP_ID}
                for context in sorted(REQUIRED_CHECKS)
            ],
        },
        "required_pull_request_reviews": {"required_approving_review_count": 0},
        "enforce_admins": {"enabled": True},
        "required_linear_history": {"enabled": True},
        "required_conversation_resolution": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    }
    private_reporting: dict[str, object] = {"enabled": True}
    milestone: dict[str, object] = {
        "title": "v0.2.0 Production readiness",
        "open_issues": 3,
        "closed_issues": 3,
    }
    release: dict[str, object] = {"tag_name": "v0.1.0", "immutable": False}
    return repository, protection, private_reporting, milestone, release


def test_valid_governance_snapshot_passes_and_reports_observations() -> None:
    report = audit_snapshot(*valid_snapshot())

    assert report["passed"] is True
    assert report["observations"] == {
        "open_issues": 4,
        "milestone": "v0.2.0 Production readiness",
        "milestone_open": 3,
        "milestone_closed": 3,
        "latest_release": "v0.1.0",
        "latest_release_immutable": False,
    }


def test_merge_and_required_check_drift_fail_independently() -> None:
    repository, protection, private_reporting, milestone, release = valid_snapshot()
    repository["allow_merge_commit"] = True
    status_checks = protection["required_status_checks"]
    assert isinstance(status_checks, dict)
    checks = status_checks["checks"]
    assert isinstance(checks, list)
    checks[0] = {"context": checks[0]["context"], "app_id": 1}

    report = audit_snapshot(repository, protection, private_reporting, milestone, release)
    checks = cast(list[dict[str, Any]], report["checks"])
    failed = {item["name"] for item in checks if not item["passed"]}

    assert report["passed"] is False
    assert failed == {"merge.commit_disabled", "protection.required_checks"}


def test_missing_nested_security_and_protection_values_fail_closed() -> None:
    repository, protection, private_reporting, milestone, release = valid_snapshot()
    repository["security_and_analysis"] = {}
    protection.pop("enforce_admins")

    report = audit_snapshot(repository, protection, private_reporting, milestone, release)
    checks = cast(list[dict[str, Any]], report["checks"])
    failed = {item["name"] for item in checks if not item["passed"]}

    assert "security.secret_scanning" in failed
    assert "security.secret_scanning_push_protection" in failed
    assert "security.dependabot_security_updates" in failed
    assert "protection.enforce_admins" in failed


@pytest.mark.parametrize("repository", ["owner", "owner/repo/extra", "owner/repo name"])
def test_client_rejects_invalid_repository_names(repository: str) -> None:
    with pytest.raises(AuditError, match="invalid repository name"):
        GitHubClient(repository, "token")


def test_client_requires_token() -> None:
    with pytest.raises(AuditError, match="TOKEN"):
        GitHubClient("owner/repo", "")
