from pipelens.models import (
    Classification,
    Diagnosis,
    ErrorCategory,
    Evidence,
    RelatedFile,
    Suggestion,
    TrustLevel,
)
from pipelens.publication import MAX_GITHUB_BODY_CHARS, render_github_diagnosis


def test_github_diagnosis_contains_required_sections_and_neutralizes_mentions() -> None:
    body = render_github_diagnosis(
        123,
        Classification(
            category=ErrorCategory.TEST,
            confidence=0.9,
            first_error="failed",
            related_step="tests",
        ),
        Diagnosis(
            summary="@team 테스트 실패",
            root_cause="assertion failed",
            confidence=0.88,
            evidence=[Evidence(source="log", content="<error> assertion failed")],
            suggestions=[Suggestion(description="테스트 수정", file="tests/test_app.py")],
        ),
        [RelatedFile(filename="tests/test_app.py", score=0.9, reasons=["로그 직접 일치"])],
        "https://pipelens.example/?run_id=123",
        baseline_sha="1234567890abcdef",
        head_sha="fedcba0987654321",
    )

    assert "### 추정 원인" in body
    assert "### 검증된 근거" in body
    assert "### 관련 변경 파일" in body
    assert "### 권장 해결 방법" in body
    assert "@\u200bteam" in body
    assert "&lt;error&gt;" in body
    assert "https://pipelens.example/?run_id=123" in body
    assert "1234567890ab..fedcba098765" in body


def test_github_diagnosis_respects_comment_size_limit() -> None:
    body = render_github_diagnosis(
        123,
        Classification(
            category=ErrorCategory.UNKNOWN, confidence=0.2, first_error="unknown"
        ),
        Diagnosis(
            summary="unknown",
            root_cause="x" * (MAX_GITHUB_BODY_CHARS + 1),
            confidence=0.2,
            evidence=[Evidence(source="log", content="unknown")],
        ),
        [],
        "https://pipelens.example/?run_id=123",
    )

    assert len(body) <= MAX_GITHUB_BODY_CHARS
    assert "내용이 길어 일부를 생략했습니다" in body


def test_github_diagnosis_warns_for_untrusted_fork() -> None:
    body = render_github_diagnosis(
        123,
        Classification(
            category=ErrorCategory.TEST, confidence=0.9, first_error="test failed"
        ),
        Diagnosis(
            summary="테스트 실패",
            root_cause="assertion failed",
            confidence=0.9,
            evidence=[Evidence(source="log", content="test failed")],
        ),
        [],
        "https://pipelens.example/?run_id=123",
        TrustLevel.UNTRUSTED_FORK,
    )

    assert "외부 Fork" in body
    assert "LLM에 전송하지 않았습니다" in body
