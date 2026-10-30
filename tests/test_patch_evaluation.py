import json
import shutil
from pathlib import Path

from pipelens.patch_evaluation import evaluate_patch_manifest

MANIFEST = Path("evaluation/patch_scenarios.json")


def test_patch_scenarios_meet_the_required_accuracy() -> None:
    report = evaluate_patch_manifest(MANIFEST)

    assert report.total == 14
    assert report.accuracy == 1.0
    assert report.verified == 5
    assert report.rejected == 6


def test_wrong_expectations_fail_the_case(tmp_path: Path) -> None:
    shutil.copytree(MANIFEST.parent / "patches", tmp_path / "patches")
    cases = json.loads(MANIFEST.read_text())
    by_id = {case["case_id"]: case for case in cases}
    by_id["rule-pip-latest-listed"]["expected_patches"] = {
        ".github/workflows/ci.yml": "pip install pip==25.3"
    }
    by_id["llm-remote-script-rejected"]["expected_note"] = "workflow 트리거"
    by_id["none-for-hash-locked-entry"]["expected_patches"] = {"requirements.txt": "50.0.2"}
    manifest = tmp_path / "patch_scenarios.json"
    manifest.write_text(json.dumps(cases))

    results = evaluate_patch_manifest(manifest).results
    failed = {result.case_id for result in results if not result.passed}

    assert failed == {
        "rule-pip-latest-listed",
        "llm-remote-script-rejected",
        "none-for-hash-locked-entry",
    }
