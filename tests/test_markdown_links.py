from __future__ import annotations

from pathlib import Path

from ops.ci.verify_markdown_links import github_slug, heading_anchors, verify_markdown


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_relative_files_directories_anchors_and_external_links_pass(tmp_path: Path) -> None:
    write(
        tmp_path / "README.md",
        "# Home\n[docs](docs/) [section](docs/guide.md#설정-api) "
        "[same](#home) [external](https://example.com/missing)\n",
    )
    write(tmp_path / "docs" / "guide.md", "# 설정: API\n")

    assert verify_markdown(tmp_path) == []


def test_missing_path_and_anchor_are_reported_with_lines(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "# Home\n[missing](none.md)\n[anchor](guide.md#missing)\n")
    write(tmp_path / "guide.md", "# Present\n")

    problems = verify_markdown(tmp_path)

    assert [(item.line, item.reason, item.target) for item in problems] == [
        (2, "missing local path", "none.md"),
        (3, "missing heading anchor", "guide.md#missing"),
    ]


def test_reference_definitions_and_percent_encoded_paths_are_checked(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "[guide]: <docs/My%20Guide.md>\n[missing]: absent.json\n")
    write(tmp_path / "docs" / "My Guide.md", "# Guide\n")

    problems = verify_markdown(tmp_path)

    assert len(problems) == 1
    assert problems[0].target == "absent.json"


def test_fenced_examples_are_ignored(tmp_path: Path) -> None:
    write(
        tmp_path / "README.md",
        "# Real\n```markdown\n[example](not-created.md)\n# Not an anchor\n```\n[ok](#real)\n",
    )

    assert verify_markdown(tmp_path) == []


def test_duplicate_headings_match_github_suffixes(tmp_path: Path) -> None:
    guide = tmp_path / "guide.md"
    write(guide, "# Repeat\n## Repeat\nRepeat\n------\n")
    write(
        tmp_path / "README.md",
        "[one](guide.md#repeat) [two](guide.md#repeat-1) [three](guide.md#repeat-2)\n",
    )

    assert heading_anchors(guide) == frozenset({"repeat", "repeat-1", "repeat-2"})
    assert verify_markdown(tmp_path) == []


def test_repository_escape_and_wrong_case_fail(tmp_path: Path) -> None:
    write(tmp_path / "Guide.md", "# Guide\n")
    write(tmp_path / "README.md", "[case](guide.md) [escape](../outside.md)\n")
    write(tmp_path.parent / "outside.md", "# Outside\n")

    problems = verify_markdown(tmp_path)

    assert {item.target for item in problems} == {"guide.md", "../outside.md"}


def test_slug_removes_markdown_and_punctuation() -> None:
    assert github_slug("`API`: 설정 & 운영!") == "api-설정--운영"
