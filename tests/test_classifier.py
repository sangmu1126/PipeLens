import pytest

from pipelens.classifier import classify_log, extract_error_context
from pipelens.models import ErrorCategory


@pytest.mark.parametrize(
    ("log", "expected"),
    [
        ("pytest: 1 failed, 9 passed", ErrorCategory.TEST),
        ("error: compilation failed", ErrorCategory.BUILD),
        ("npm ERR! ERESOLVE unable to resolve dependency tree", ErrorCategory.DEPENDENCY),
        ("ruff check failed with lint errors", ErrorCategory.LINT),
        ("docker build failed: Dockerfile:12", ErrorCategory.DOCKER),
        ("deploy failed: invalid credentials", ErrorCategory.DEPLOY_AUTH),
        ("required environment variable DATABASE_URL not set", ErrorCategory.MISSING_ENV),
        ("operation timed out", ErrorCategory.TIMEOUT),
        ("fatal: no space left on device", ErrorCategory.RESOURCE),
        ("Invalid workflow file: YAML syntax error", ErrorCategory.WORKFLOW),
    ],
)
def test_required_error_categories(log: str, expected: ErrorCategory) -> None:
    result = classify_log(log, related_step="test")

    assert result.category == expected
    assert result.matched_rules
    assert result.related_step == "test"


def test_extract_error_context_omits_unrelated_lines() -> None:
    log = "\n".join([*(f"setup {i}" for i in range(20)), "fatal error here", "tail"])

    result = extract_error_context(log, context_lines=2)

    assert "setup 0" not in result
    assert "setup 18" in result
    assert "fatal error here" in result


def test_classification_keeps_first_rule_match_over_downstream_failure() -> None:
    result = classify_log(
        "npm ERR! ERESOLVE unable to resolve dependency tree\n"
        "cleanup failed with exit code 137"
    )

    assert result.category is ErrorCategory.DEPENDENCY
    assert result.first_error.startswith("npm ERR!")
