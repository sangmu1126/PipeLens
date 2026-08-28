from pipelens.models import ChangedFile, ErrorCategory
from pipelens.relevance import correlate_changed_files


def test_direct_log_path_ranks_changed_file_first() -> None:
    changed_files = [
        ChangedFile(
            filename="src/payments/service.py",
            status="modified",
            patch="@@ -1 +1 @@\n-charge(card)\n+charge(payment_method)",
        ),
        ChangedFile(filename="tests/test_checkout.py", status="modified"),
    ]
    log = "src/payments/service.py:42: NameError: payment_method is not defined"

    result = correlate_changed_files(log, changed_files, ErrorCategory.TEST)

    assert result[0].filename == "src/payments/service.py"
    assert result[0].score == 0.9
    assert "+charge(payment_method)" in result[0].patch_excerpt
    assert result[1].filename == "tests/test_checkout.py"


def test_no_weak_guess_when_files_do_not_match() -> None:
    result = correlate_changed_files(
        "network connection reset",
        [ChangedFile(filename="docs/architecture.md", status="modified")],
        ErrorCategory.UNKNOWN,
    )

    assert result == []


def test_dependency_category_recognizes_lockfile() -> None:
    result = correlate_changed_files(
        "npm ERR! unable to resolve dependency tree",
        [ChangedFile(filename="package-lock.json", status="modified")],
        ErrorCategory.DEPENDENCY,
    )

    assert result[0].score == 0.2
    assert "패키지 설정" in result[0].reasons[0]


def test_patch_excerpt_is_redacted_before_it_is_returned() -> None:
    result = correlate_changed_files(
        "API_KEY was rejected in src/config.py",
        [
            ChangedFile(
                filename="src/config.py",
                status="modified",
                patch="@@ -1 +1 @@\n+API_KEY=super-secret-value",
            )
        ],
        ErrorCategory.DEPLOY_AUTH,
    )

    assert result[0].patch_excerpt == "+API_KEY=[REDACTED]"
