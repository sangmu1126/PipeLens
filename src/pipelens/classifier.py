import re
from dataclasses import dataclass

from pipelens.models import Classification, ErrorCategory


@dataclass(frozen=True)
class DetectionRule:
    rule_id: str
    category: ErrorCategory
    confidence: float
    patterns: tuple[re.Pattern[str], ...]


def _patterns(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(value, re.I) for value in values)


RULES = (
    DetectionRule(
        "env.missing",
        ErrorCategory.MISSING_ENV,
        0.94,
        _patterns(
            r"(?:keyerror|missing|required).*env",
            r"(?:environment variable|env var).*not (?:set|found|defined)",
            r"\$\{\{\s*secrets\.[^}]+\}\}.*(?:not found|empty)",
        ),
    ),
    DetectionRule(
        "auth.deploy",
        ErrorCategory.DEPLOY_AUTH,
        0.92,
        _patterns(
            r"(?:unauthorized|forbidden|access denied|invalid credentials)",
            r"authentication required",
            r"denied: requested access",
        ),
    ),
    DetectionRule(
        "resource.exhaustion",
        ErrorCategory.RESOURCE,
        0.96,
        _patterns(
            r"no space left on device",
            r"out of memory|oomkilled|cannot allocate memory",
            r"exit code 137",
        ),
    ),
    DetectionRule(
        "timeout",
        ErrorCategory.TIMEOUT,
        0.91,
        _patterns(
            r"timed? out|timeout exceeded",
            r"deadline exceeded",
            r"job was cancelled because.*timeout",
        ),
    ),
    DetectionRule(
        "workflow.syntax",
        ErrorCategory.WORKFLOW,
        0.95,
        _patterns(
            r"invalid workflow file",
            r"yaml(?: syntax| parser)? error",
            r"unrecognized named-value",
            r"the workflow is not valid",
        ),
    ),
    DetectionRule(
        "dependency.install",
        ErrorCategory.DEPENDENCY,
        0.90,
        _patterns(
            r"(?:npm err!|eresolve unable to resolve dependency tree)",
            r"could not find a version that satisfies",
            r"failed (?:building wheel|to resolve dependencies)",
            r"package .* has no installation candidate",
        ),
    ),
    DetectionRule(
        "docker.build",
        ErrorCategory.DOCKER,
        0.89,
        _patterns(
            r"docker build.*failed",
            r"failed to solve: process",
            r"dockerfile:\d+",
            r"error response from daemon",
        ),
    ),
    DetectionRule(
        "lint.format",
        ErrorCategory.LINT,
        0.88,
        _patterns(
            r"(?:eslint|ruff|flake8|prettier|black).*?(?:error|failed)",
            r"would reformat",
            r"lint(?:ing)? failed",
            r"code style issues found",
        ),
    ),
    DetectionRule(
        "test.failure",
        ErrorCategory.TEST,
        0.90,
        _patterns(
            r"\b(?:failed|failures?)\b.*\btests?\b",
            r"(?:pytest|jest|vitest|rspec).*failed",
            r"assertionerror|expected .* (?:to|but)",
        ),
    ),
    DetectionRule(
        "build.compile",
        ErrorCategory.BUILD,
        0.87,
        _patterns(
            r"(?:compilation|compile|build) failed",
            r"syntaxerror|typeerror:.*(?:assignable|property)",
            r"undefined reference",
            r"cannot find symbol",
        ),
    ),
)

ERROR_LINE = re.compile(r"(?:error|exception|failed|fatal|panic|timeout|denied|not found)", re.I)


def classify_log(log: str, related_step: str | None = None) -> Classification:
    lines = [line.strip() for line in log.splitlines() if line.strip()]
    first_error = next(
        (line for line in lines if ERROR_LINE.search(line)),
        lines[0] if lines else "No error output was captured",
    )

    best_rule: DetectionRule | None = None
    best_line = first_error
    for line in lines:
        for rule in RULES:
            if any(pattern.search(line) for pattern in rule.patterns) and (
                best_rule is None or rule.confidence > best_rule.confidence
            ):
                best_rule = rule
                best_line = line

    if best_rule is None:
        return Classification(
            category=ErrorCategory.UNKNOWN,
            confidence=0.2,
            first_error=first_error,
            related_step=related_step,
        )

    return Classification(
        category=best_rule.category,
        confidence=best_rule.confidence,
        first_error=best_line,
        related_step=related_step,
        matched_rules=[best_rule.rule_id],
    )


def extract_error_context(log: str, context_lines: int = 8, max_sections: int = 5) -> str:
    lines = log.splitlines()
    indexes = [index for index, line in enumerate(lines) if ERROR_LINE.search(line)]
    if not indexes:
        return "\n".join(lines[-min(len(lines), context_lines * 2) :])

    ranges: list[tuple[int, int]] = []
    for index in indexes[:max_sections]:
        start, end = max(0, index - context_lines), min(len(lines), index + context_lines + 1)
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return "\n...\n".join("\n".join(lines[start:end]) for start, end in ranges)
