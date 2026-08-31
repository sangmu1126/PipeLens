from pathlib import Path

from pipelens.evaluation import evaluate_manifest


def test_mvp_failure_scenarios_meet_accuracy_target() -> None:
    report = evaluate_manifest(Path("evaluation/scenarios.json"), chunk_chars=128)

    assert report.total == 12
    assert report.passed >= 10
    assert report.accuracy >= 0.8
