from pipelens.diagnosis import build_rule_based_diagnosis, validate_diagnosis
from pipelens.models import Classification, ErrorCategory, Evidence


def test_rule_diagnosis_always_has_grounded_evidence() -> None:
    classification = Classification(
        category=ErrorCategory.TIMEOUT,
        confidence=0.91,
        first_error="operation timed out",
        matched_rules=["timeout"],
    )

    diagnosis = validate_diagnosis(
        build_rule_based_diagnosis(classification), "before\noperation timed out\nafter"
    )

    assert diagnosis.root_cause != "확인 불가"
    assert diagnosis.evidence[0].content == "operation timed out"


def test_ungrounded_evidence_downgrades_diagnosis() -> None:
    classification = Classification(
        category=ErrorCategory.BUILD,
        confidence=0.9,
        first_error="real compiler error",
    )
    diagnosis = build_rule_based_diagnosis(classification)
    diagnosis.evidence = [Evidence(source="log", content="invented compiler error")]

    result = validate_diagnosis(diagnosis, "real compiler error")

    assert result.root_cause == "확인 불가"
    assert result.confidence == 0.3
    assert result.evidence == []
    assert result.conflicts
