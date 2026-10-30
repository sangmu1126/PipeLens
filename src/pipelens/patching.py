import difflib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import PurePosixPath

import yaml

from pipelens.models import Diagnosis, Suggestion, SuggestionSource
from pipelens.sanitizer import sanitize_log

MAX_PATCH_CHARS = 20_000
MAX_CHANGED_LINES = 200
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
PIP_UNSATISFIED = re.compile(
    r"could not find a version that satisfies the requirement "
    r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;,()]+).*\(from versions: ([^)]*)\)",
    re.I,
)
TABLE_SEPARATOR = re.compile(r"\s*[│|]\s*")
VERSION_TOKEN = re.compile(r"^[0-9][A-Za-z0-9.+_:~-]*$")
PINNED_VERSION_VALUE = re.compile(r"==[^\s;,\"'\\]+")
WORKFLOW_PREFIX = ".github/workflows/"
STRUCTURED_FORMATS = {".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".json": "JSON"}

# Added lines that no published fix may introduce, whatever produced the diff.
FORBIDDEN_ADDITIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "원격 스크립트를 셸로 실행",
        re.compile(
            r"\b(?:curl|wget)\b[^\n]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b"
            r"|\b(?:ba|z)?sh\b[^\n]*\$\((?:curl|wget)\b",
            re.I,
        ),
    ),
    (
        "secret·토큰 참조",
        re.compile(
            r"\$\{\{\s*(?:secrets\.|github\.token)"
            r"|\b(?:GITHUB_TOKEN|ACTIONS_RUNTIME_TOKEN|ACTIONS_ID_TOKEN_REQUEST_TOKEN)\b",
            re.I,
        ),
    ),
    ("인코딩된 명령 실행", re.compile(r"\bbase64\s+(?:-d|--decode)\b|\beval\s", re.I)),
    ("실행 권한 추가", re.compile(r"\bchmod\s+(?:[ugoa]*\+x|0?[0-7]*[1357][0-7]*)\b", re.I)),
)
# Workflow lines whose addition or removal changes privileges or triggers.
WORKFLOW_SENSITIVE: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "workflow 권한 변경",
        re.compile(
            r"^\s*permissions\s*:|\b(?:actions|checks|contents|deployments|id-token|issues|"
            r"packages|pull-requests|security-events|statuses)\s*:\s*(?:read|write)\b",
            re.I,
        ),
    ),
    (
        "workflow 트리거 변경",
        re.compile(r"^\s*on\s*:|\b(?:pull_request_target|workflow_run)\b", re.I),
    ),
)


class PatchError(ValueError):
    pass


@dataclass(frozen=True)
class VersionBump:
    package: str
    current: str
    target: str
    reason: str


@dataclass(frozen=True)
class _Hunk:
    old_start: int
    old_lines: list[str]
    new_lines: list[str]


def apply_unified_diff(original: str, patch: str) -> str:
    """Apply a single-file unified diff, requiring every context and removed line to match."""
    hunks = _parse_hunks(patch)
    lines = original.splitlines(keepends=True)
    result: list[str] = []
    cursor = 0
    for hunk in hunks:
        start = _locate_hunk(lines, hunk, cursor)
        result.extend(lines[cursor:start])
        result.extend(hunk.new_lines)
        cursor = start + len(hunk.old_lines)
    result.extend(lines[cursor:])
    return "".join(result)


def render_unified_diff(path: str, original: str, updated: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=2,
        )
    )


def find_version_bumps(log: str) -> list[VersionBump]:
    bumps: list[VersionBump] = []
    for line in log.splitlines():
        pip_match = PIP_UNSATISFIED.search(line)
        if pip_match:
            package, current, listed = pip_match.groups()
            versions = [item.strip() for item in listed.split(",") if item.strip()]
            available = [item for item in versions if VERSION_TOKEN.match(item)]
            if available:
                bumps.append(
                    VersionBump(package, current, available[-1], "설치 가능한 최신 버전")
                )
            continue
        bump = _scanner_row_bump(line)
        if bump:
            bumps.append(bump)
    unique: dict[tuple[str, str], VersionBump] = {}
    for bump in bumps:
        unique.setdefault((bump.package.lower(), bump.current), bump)
    return list(unique.values())


def propose_version_patches(
    bumps: list[VersionBump], files: dict[str, str]
) -> tuple[list[Suggestion], list[str]]:
    suggestions: list[Suggestion] = []
    notes: list[str] = []
    for bump in bumps:
        pattern = re.compile(
            rf"(?<![A-Za-z0-9._-]){re.escape(bump.package)}"
            rf"=={re.escape(bump.current)}(?![0-9A-Za-z.+])",
            re.I,
        )
        for path, content in sorted(files.items()):
            if not pattern.search(content):
                continue
            if _is_hash_locked(content, pattern):
                notes.append(
                    f"`{path}`의 {bump.package}=={bump.current}는 해시가 고정된 lock 항목이라 "
                    "diff를 만들지 않았습니다. 버전을 올린 뒤 lock을 다시 생성하세요."
                )
                continue
            updated = pattern.sub(f"{bump.package}=={bump.target}", content)
            suggestions.append(
                Suggestion(
                    description=(
                        f"{bump.package}를 {bump.current}에서 {bump.target}로 변경하세요 "
                        f"({bump.reason})."
                    ),
                    file=path,
                    patch=render_unified_diff(path, content, updated),
                    source=SuggestionSource.RULE,
                )
            )
    return suggestions, notes


def verify_patch_suggestions(
    diagnosis: Diagnosis, files: dict[str, str]
) -> tuple[Diagnosis, dict[tuple[str, str], int]]:
    """Keep a patch only when it applies to the fetched head content and is safe to publish."""
    outcomes: dict[tuple[str, str], int] = {}
    suggestions: list[Suggestion] = []
    notes = list(diagnosis.notes)
    for suggestion in diagnosis.suggestions:
        if not suggestion.patch:
            suggestions.append(suggestion)
            continue
        source = (suggestion.source or SuggestionSource.LLM).value
        rejection = _patch_rejection(suggestion, files)
        if rejection is None:
            suggestions.append(suggestion.model_copy(update={"patch_verified": True}))
            outcomes[(source, "verified")] = outcomes.get((source, "verified"), 0) + 1
            continue
        suggestions.append(suggestion.model_copy(update={"patch": None, "patch_verified": False}))
        notes.append(f"수정 diff를 검증하지 못해 제외했습니다: {rejection}")
        outcomes[(source, "rejected")] = outcomes.get((source, "rejected"), 0) + 1
    return diagnosis.model_copy(update={"suggestions": suggestions, "notes": notes}), outcomes


def strip_patches(diagnosis: Diagnosis) -> Diagnosis:
    suggestions = [
        item.model_copy(update={"patch": None, "patch_verified": False})
        for item in diagnosis.suggestions
    ]
    return diagnosis.model_copy(update={"suggestions": suggestions})


def _patch_rejection(suggestion: Suggestion, files: dict[str, str]) -> str | None:
    patch = suggestion.patch or ""
    if not suggestion.file or suggestion.file not in files:
        return "대상 파일을 head 기준으로 확인할 수 없습니다."
    if len(patch) > MAX_PATCH_CHARS:
        return "diff가 허용 크기를 넘습니다."
    changed = [
        line
        for line in patch.splitlines()
        if line[:1] in {"+", "-"} and not line.startswith(("+++", "---"))
    ]
    if not changed or len(changed) > MAX_CHANGED_LINES:
        return "diff의 변경 줄 수가 허용 범위를 벗어납니다."
    allowed_headers = {f"a/{suggestion.file}", f"b/{suggestion.file}", suggestion.file}
    headers = [line[4:].strip() for line in patch.splitlines() if line.startswith(("+++", "---"))]
    if any(header not in allowed_headers for header in headers):
        return "diff가 제안 대상 외의 파일을 가리킵니다."
    _, redactions = sanitize_log(patch)
    if redactions:
        return "diff에 비밀값으로 보이는 내용이 포함돼 있습니다."
    violation = _policy_violation(suggestion, patch)
    if violation:
        return f"diff에 허용되지 않는 변경이 포함돼 있습니다({violation})."
    try:
        updated = apply_unified_diff(files[suggestion.file], patch)
    except PatchError as exc:
        return str(exc)
    return _syntax_error(suggestion.file, updated)


def _policy_violation(suggestion: Suggestion, patch: str) -> str | None:
    body = [line for line in patch.splitlines() if not line.startswith(("+++", "---"))]
    added = [line[1:] for line in body if line.startswith("+")]
    removed = [line[1:] for line in body if line.startswith("-")]
    if suggestion.source is SuggestionSource.RULE and (
        len(added) != len(removed)
        or any(
            PINNED_VERSION_VALUE.sub("==", new) != PINNED_VERSION_VALUE.sub("==", old)
            for old, new in zip(removed, added, strict=True)
        )
    ):
        return "규칙 diff가 버전 문자열 외의 내용을 바꿈"
    for label, pattern in FORBIDDEN_ADDITIONS:
        if any(pattern.search(line) for line in added):
            return label
    if (suggestion.file or "").startswith(WORKFLOW_PREFIX):
        for label, pattern in WORKFLOW_SENSITIVE:
            if any(pattern.search(line) for line in added + removed):
                return label
    return None


def _syntax_error(path: str, content: str) -> str | None:
    format_name = STRUCTURED_FORMATS.get(PurePosixPath(path).suffix.lower())
    try:
        if format_name == "YAML":
            list(yaml.safe_load_all(content))
        elif format_name == "TOML":
            tomllib.loads(content)
        elif format_name == "JSON":
            json.loads(content)
    except (yaml.YAMLError, tomllib.TOMLDecodeError, json.JSONDecodeError):
        return f"수정 결과가 유효한 {format_name} 문서가 아닙니다."
    return None


def _parse_hunks(patch: str) -> list[_Hunk]:
    hunks: list[_Hunk] = []
    current: _Hunk | None = None
    for raw in patch.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        header = HUNK_HEADER.match(line)
        if header:
            current = _Hunk(old_start=int(header.group(1)), old_lines=[], new_lines=[])
            hunks.append(current)
            continue
        if line.startswith(("---", "+++", "diff ", "index ")) and current is None:
            continue
        if current is None:
            if line.strip():
                raise PatchError("diff에 hunk 헤더가 없습니다.")
            continue
        if line.startswith("\\"):
            continue
        marker, body = (line[:1], raw[1:]) if line else (" ", "\n")
        if marker == " ":
            current.old_lines.append(body)
            current.new_lines.append(body)
        elif marker == "-":
            current.old_lines.append(body)
        elif marker == "+":
            current.new_lines.append(body)
        else:
            raise PatchError("diff에 해석할 수 없는 줄이 있습니다.")
    if not hunks:
        raise PatchError("diff에 hunk가 없습니다.")
    return hunks


def _locate_hunk(lines: list[str], hunk: _Hunk, cursor: int) -> int:
    expected = [_strip_newline(line) for line in hunk.old_lines]
    size = len(expected)

    def matches(start: int) -> bool:
        window = lines[start : start + size]
        return len(window) == size and [_strip_newline(line) for line in window] == expected

    stated = max(hunk.old_start - 1, 0)
    if stated >= cursor and matches(stated):
        return stated
    candidates = [start for start in range(cursor, len(lines) - size + 1) if matches(start)]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise PatchError("diff의 기존 줄이 head 파일 내용과 일치하지 않습니다.")
    raise PatchError("diff를 적용할 위치가 하나로 정해지지 않습니다.")


def _strip_newline(line: str) -> str:
    return line.rstrip("\r\n")


def _is_hash_locked(content: str, pattern: re.Pattern[str]) -> bool:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if not pattern.search(line):
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if "--hash=" in line or following.strip().startswith("--hash="):
            return True
    return False


def _scanner_row_bump(line: str) -> VersionBump | None:
    if "│" not in line and line.count("|") < 6:
        return None
    cells = [
        cell.strip() for cell in TABLE_SEPARATOR.split(line.strip().strip("│|")) if cell.strip()
    ]
    if len(cells) < 6 or cells[3].lower() != "fixed":
        return None
    package = re.sub(r"\s*\(.*\)$", "", cells[0])
    current = cells[4]
    target = cells[5].split(",")[0].strip()
    if not (VERSION_TOKEN.match(current) and VERSION_TOKEN.match(target)) or current == target:
        return None
    return VersionBump(package, current, target, f"{cells[1]} 수정 버전")
