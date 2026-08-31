from pathlib import Path

from ops.ci.verify_action_pinning import find_mutable_actions


def test_action_pinning_accepts_sha_and_local_references(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    workflows.joinpath("ci.yml").write_text(
        "steps:\n"
        "  - uses: actions/checkout@" + "a" * 40 + " # v7\n"
        "  - uses: ./local-action\n"
        "  - uses: docker://alpine:3.23\n",
        encoding="utf-8",
    )

    assert find_mutable_actions(workflows) == []


def test_action_pinning_reports_mutable_references_with_locations(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    workflows.joinpath("ci.yaml").write_text(
        "steps:\n  - uses: actions/checkout@v7\n  - uses: owner/action@v1.2.3\n",
        encoding="utf-8",
    )

    assert find_mutable_actions(workflows) == [
        f"{workflows / 'ci.yaml'}:2: actions/checkout@v7",
        f"{workflows / 'ci.yaml'}:3: owner/action@v1.2.3",
    ]
