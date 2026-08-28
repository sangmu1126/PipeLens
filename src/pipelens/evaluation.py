import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from pipelens.classifier import classify_log
from pipelens.models import ErrorCategory
from pipelens.preprocessing import preprocess_log


class EvaluationCase(BaseModel):
    case_id: str
    log_file: str
    expected_category: ErrorCategory
    expected_evidence: str


class EvaluationResult(BaseModel):
    case_id: str
    expected_category: ErrorCategory
    actual_category: ErrorCategory
    category_correct: bool
    evidence_correct: bool
    first_error: str

    @property
    def passed(self) -> bool:
        return self.category_correct and self.evidence_correct


class EvaluationReport(BaseModel):
    results: list[EvaluationResult]

    @property
    def passed(self) -> int:
        return sum(result.passed for result in self.results)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0


def evaluate_manifest(
    manifest_path: Path,
    chunk_chars: int = 200_000,
    context_lines: int = 8,
    max_error_chunks: int = 10,
) -> EvaluationReport:
    raw_cases = json.loads(manifest_path.read_text())
    cases = [EvaluationCase.model_validate(item) for item in raw_cases]
    results: list[EvaluationResult] = []
    for case in cases:
        raw_log = (manifest_path.parent / case.log_file).read_text()
        processed = preprocess_log(
            raw_log,
            chunk_chars=chunk_chars,
            context_lines=context_lines,
            max_error_chunks=max_error_chunks,
        )
        classification = classify_log(processed.context)
        results.append(
            EvaluationResult(
                case_id=case.case_id,
                expected_category=case.expected_category,
                actual_category=classification.category,
                category_correct=classification.category is case.expected_category,
                evidence_correct=case.expected_evidence in classification.first_error,
                first_error=classification.first_error,
            )
        )
    return EvaluationReport(results=results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate PipeLens failure classification")
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=Path("evaluation/scenarios.json"),
    )
    parser.add_argument("--minimum-accuracy", type=float, default=0.8)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = evaluate_manifest(args.manifest)
    if args.as_json:
        print(report.model_dump_json(indent=2))
    else:
        for result in report.results:
            marker = "PASS" if result.passed else "FAIL"
            print(
                f"[{marker}] {result.case_id}: "
                f"{result.actual_category.value} (expected {result.expected_category.value})"
            )
        print(f"\nAccuracy: {report.passed}/{report.total} ({report.accuracy:.0%})")
    if report.accuracy < args.minimum_accuracy:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
