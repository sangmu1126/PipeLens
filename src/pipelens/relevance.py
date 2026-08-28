import re
from pathlib import PurePosixPath

from pipelens.models import ChangedFile, ErrorCategory, RelatedFile
from pipelens.sanitizer import sanitize_log

TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{2,}")
PATCH_LINE = re.compile(r"^[+-](?![+-])")
STOP_WORDS = {
    "error",
    "failed",
    "failure",
    "fatal",
    "file",
    "line",
    "with",
    "from",
    "this",
    "that",
}


def correlate_changed_files(
    log: str,
    changed_files: list[ChangedFile],
    category: ErrorCategory,
    limit: int = 5,
) -> list[RelatedFile]:
    lowered_log = log.lower()
    log_tokens = _tokens(log)
    results: list[RelatedFile] = []

    for changed in changed_files:
        path = PurePosixPath(changed.filename)
        reasons: list[str] = []
        score = 0.0

        if changed.filename.lower() in lowered_log:
            score += 0.75
            reasons.append("로그에 변경 파일 경로가 직접 등장함")
        elif path.name.lower() in lowered_log:
            score += 0.5
            reasons.append("로그에 변경 파일명이 등장함")

        category_score, category_reason = _category_affinity(path, category)
        if category_score:
            score += category_score
            reasons.append(category_reason)

        patch_excerpt = _matching_patch_excerpt(changed.patch, log_tokens)
        if patch_excerpt:
            score += 0.15
            reasons.append("오류 로그와 변경 코드가 공통 식별자를 포함함")

        if reasons:
            results.append(
                RelatedFile(
                    filename=changed.filename,
                    score=min(score, 1.0),
                    reasons=reasons,
                    patch_excerpt=patch_excerpt,
                )
            )

    return sorted(results, key=lambda item: (-item.score, item.filename))[:limit]


def _category_affinity(path: PurePosixPath, category: ErrorCategory) -> tuple[float, str]:
    lowered = str(path).lower()
    if category is ErrorCategory.TEST and (
        "test" in path.name.lower() or any(part in {"test", "tests", "spec"} for part in path.parts)
    ):
        return 0.2, "테스트 실패 범주와 테스트 파일이 일치함"
    if category is ErrorCategory.WORKFLOW and lowered.startswith(".github/workflows/"):
        return 0.3, "Workflow 오류 범주와 Actions 설정 파일이 일치함"
    if category is ErrorCategory.DOCKER and path.name.lower().startswith("dockerfile"):
        return 0.25, "Docker 실패 범주와 Dockerfile이 일치함"
    if category is ErrorCategory.DEPENDENCY and path.name.lower() in {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "poetry.lock",
        "requirements.txt",
        "pyproject.toml",
    }:
        return 0.2, "의존성 실패 범주와 패키지 설정 파일이 일치함"
    return 0.0, ""


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN.finditer(text)} - STOP_WORDS


def _matching_patch_excerpt(patch: str | None, log_tokens: set[str]) -> str | None:
    if not patch or not log_tokens:
        return None
    matches: list[str] = []
    for line in patch.splitlines():
        if PATCH_LINE.match(line) and _tokens(line) & log_tokens:
            matches.append(line[:300])
        if len(matches) == 3:
            break
    if not matches:
        return None
    sanitized, _ = sanitize_log("\n".join(matches))
    return sanitized
