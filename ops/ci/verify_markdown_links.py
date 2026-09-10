"""Verify repository-local Markdown links and heading anchors without network access."""

from __future__ import annotations

import argparse
import html
import re
import sys
import unicodedata
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

IGNORED_DIRECTORIES = frozenset(
    {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "node_modules"}
)
INLINE_LINK = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
REFERENCE_DEFINITION = re.compile(r"^\s{0,3}\[[^]]+\]:\s*(\S+)")
ATX_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
SETEXT_HEADING = re.compile(r"^\s{0,3}(?:=+|-+)\s*$")
HTML_TAG = re.compile(r"<[^>]+>")
MARKDOWN_DECORATION = re.compile(r"[`*_~]")


@dataclass(frozen=True, order=True)
class Problem:
    source: Path
    line: int
    target: str
    reason: str

    def render(self, root: Path) -> str:
        return f"{self.source.relative_to(root)}:{self.line}: {self.reason}: {self.target}"


def discover_markdown(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if not any(part in IGNORED_DIRECTORIES for part in path.relative_to(root).parts)
    )


def visible_lines(path: Path) -> list[tuple[int, str]]:
    """Return lines outside fenced code blocks."""
    result: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        marker = stripped[:1]
        if marker in {"`", "~"}:
            length = len(stripped) - len(stripped.lstrip(marker))
            if length >= 3:
                if fence is None:
                    fence = (marker, length)
                elif marker == fence[0] and length >= fence[1]:
                    fence = None
                continue
        if fence is None:
            result.append((number, line))
    return result


def github_slug(value: str) -> str:
    value = html.unescape(HTML_TAG.sub("", value)).strip().lower()
    value = MARKDOWN_DECORATION.sub("", value)
    value = re.sub(r"!?\[([^]]*)\]\([^)]+\)", r"\1", value)
    value = "".join(
        character
        for character in value
        if character in {"-", "_", " "} or not unicodedata.category(character).startswith("P")
    )
    return "".join("-" if character.isspace() else character for character in value)


def heading_anchors(path: Path) -> frozenset[str]:
    lines = visible_lines(path)
    headings: list[str] = []
    for index, (_, line) in enumerate(lines):
        match = ATX_HEADING.match(line)
        if match:
            headings.append(match.group(1))
        elif index > 0 and SETEXT_HEADING.match(line) and lines[index - 1][1].strip():
            headings.append(lines[index - 1][1].strip())

    counts: dict[str, int] = {}
    anchors: set[str] = set()
    for heading in headings:
        base = github_slug(heading)
        suffix = counts.get(base, 0)
        anchors.add(base if suffix == 0 else f"{base}-{suffix}")
        counts[base] = suffix + 1
    return frozenset(anchors)


def link_destination(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<"):
        closing = raw.find(">")
        return raw[1:closing] if closing >= 0 else raw
    return raw.split(maxsplit=1)[0]


def is_external(target: str) -> bool:
    parsed = urllib.parse.urlsplit(target)
    return bool(parsed.scheme or parsed.netloc or target.startswith("/"))


def exact_path_exists(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    current = root.resolve()
    for part in relative.parts:
        try:
            names = {child.name for child in current.iterdir()}
        except OSError:
            return False
        if part not in names:
            return False
        current /= part
    return True


def verify_markdown(root: Path, paths: list[Path] | None = None) -> list[Problem]:
    root = root.resolve()
    markdown = (
        discover_markdown(root) if paths is None else sorted(path.resolve() for path in paths)
    )
    anchor_cache: dict[Path, frozenset[str]] = {}
    problems: list[Problem] = []

    for source in markdown:
        for line_number, line in visible_lines(source):
            targets = [match.group(1) for match in INLINE_LINK.finditer(line)]
            definition = REFERENCE_DEFINITION.match(line)
            if definition:
                targets.append(definition.group(1))
            for raw_target in targets:
                target = link_destination(raw_target)
                if not target or is_external(target):
                    continue
                decoded = urllib.parse.unquote(target)
                path_value, separator, fragment = decoded.partition("#")
                candidate = source if not path_value else source.parent / path_value
                if not exact_path_exists(root, candidate):
                    problems.append(Problem(source, line_number, target, "missing local path"))
                    continue
                resolved = candidate.resolve()
                if separator and fragment:
                    if not resolved.is_file() or resolved.suffix.lower() != ".md":
                        problems.append(
                            Problem(source, line_number, target, "anchor target is not Markdown")
                        )
                        continue
                    anchors = anchor_cache.setdefault(resolved, heading_anchors(resolved))
                    if fragment not in anchors:
                        problems.append(
                            Problem(source, line_number, target, "missing heading anchor")
                        )
    return sorted(problems)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    problems = verify_markdown(root)
    if problems:
        print("Markdown integrity check failed:", file=sys.stderr)
        for problem in problems:
            print(problem.render(root), file=sys.stderr)
        return 1
    print(f"Markdown integrity check passed: {len(discover_markdown(root))} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
