import argparse
import json
from pathlib import Path

from pydantic import BaseModel, Field

from pipelens.models import Diagnosis, Evidence, Suggestion, SuggestionSource
from pipelens.patching import apply_unified_diff, find_version_bumps, propose_and_verify_patches
from pipelens.preprocessing import preprocess_log


class CandidatePatch(BaseModel):
    file: str
    patch_file: str


class PatchEvaluationCase(BaseModel):
    case_id: str
    log_file: str
    files: dict[str, str]
    candidates: list[CandidatePatch] = Field(default_factory=list)
    expected_patches: dict[str, str]
    expected_rejections: int | None = None
    expected_note: str | None = None


class PatchEvaluationResult(BaseModel):
    case_id: str
    expected_files: list[str]
    verified_files: list[str]
    content_correct: bool
    expected_rejections: int | None
    rejections: int
    note_correct: bool

    @property
    def passed(self) -> bool:
        rejections_correct = (
            self.expected_rejections is None or self.rejections == self.expected_rejections
        )
        return (
            self.verified_files == self.expected_files
            and self.content_correct
            and rejections_correct
            and self.note_correct
        )


class PatchEvaluationReport(BaseModel):
    results: list[PatchEvaluationResult]

    @property
    def passed(self) -> int:
        return sum(result.passed for result in self.results)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0

    @property
    def verified(self) -> int:
        return sum(len(result.verified_files) for result in self.results)

    @property
    def rejected(self) -> int:
        return sum(result.rejections for result in self.results)


def evaluate_patch_manifest(manifest_path: Path) -> PatchEvaluationReport:
    base = manifest_path.parent / "patches"
    raw_cases = json.loads(manifest_path.read_text())
    cases = [PatchEvaluationCase.model_validate(item) for item in raw_cases]
    results: list[PatchEvaluationResult] = []
    for case in cases:
        log = preprocess_log(
            (base / case.log_file).read_text(),
            chunk_chars=200_000,
            context_lines=8,
            max_error_chunks=10,
        ).context
        files = {path: (base / source).read_text() for path, source in case.files.items()}
        diagnosis = Diagnosis(
            summary="evaluation",
            root_cause="evaluation",
            confidence=1,
            evidence=[Evidence(source="log", content=log[:200])],
            suggestions=[
                Suggestion(
                    description=candidate.patch_file,
                    file=candidate.file,
                    patch=(base / candidate.patch_file).read_text(),
                    source=SuggestionSource.LLM,
                )
                for candidate in case.candidates
            ],
        )
        verified, outcomes = propose_and_verify_patches(diagnosis, find_version_bumps(log), files)
        accepted = [item for item in verified.suggestions if item.patch_verified and item.file]
        content_correct = all(
            any(
                expected in apply_unified_diff(files[item.file], item.patch or "")
                for item in accepted
                if item.file == path
            )
            for path, expected in case.expected_patches.items()
        )
        results.append(
            PatchEvaluationResult(
                case_id=case.case_id,
                expected_files=sorted(case.expected_patches),
                verified_files=sorted({item.file for item in accepted if item.file}),
                content_correct=content_correct,
                expected_rejections=case.expected_rejections,
                rejections=sum(
                    count for (_, outcome), count in outcomes.items() if outcome == "rejected"
                ),
                note_correct=case.expected_note is None
                or any(case.expected_note in note for note in verified.notes),
            )
        )
    return PatchEvaluationReport(results=results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate PipeLens fix diff proposals")
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=Path("evaluation/patch_scenarios.json"),
    )
    parser.add_argument("--minimum-accuracy", type=float, default=1.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = evaluate_patch_manifest(args.manifest)
    if args.as_json:
        print(
            json.dumps(
                {
                    "passed": report.passed,
                    "total": report.total,
                    "accuracy": report.accuracy,
                    "verified_patches": report.verified,
                    "rejected_patches": report.rejected,
                    "results": [
                        result.model_dump(mode="json") | {"passed": result.passed}
                        for result in report.results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for result in report.results:
            marker = "PASS" if result.passed else "FAIL"
            print(
                f"[{marker}] {result.case_id}: verified={result.verified_files} "
                f"rejected={result.rejections}"
            )
        print(
            f"\nAccuracy: {report.passed}/{report.total} ({report.accuracy:.0%}); "
            f"verified {report.verified}, rejected {report.rejected}"
        )
    if report.accuracy < args.minimum_accuracy:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
