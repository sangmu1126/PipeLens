import re
from dataclasses import dataclass

ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
TIMESTAMP_PREFIX = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+|\[\d{2}:\d{2}:\d{2}\]\s*)"
)


@dataclass(frozen=True)
class RedactionRule:
    name: str
    pattern: re.Pattern[str]
    replacement: str


REDACTION_RULES = (
    RedactionRule(
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
        "[REDACTED:GITHUB_TOKEN]",
    ),
    RedactionRule(
        "aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED:AWS_ACCESS_KEY]"
    ),
    RedactionRule(
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        "[REDACTED:JWT]",
    ),
    RedactionRule(
        "authorization",
        re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+|basic\s+)?\S+"),
        r"\1[REDACTED]",
    ),
    RedactionRule(
        "secret_assignment",
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_KEY|ACCESS_TOKEN|PRIVATE_KEY)[A-Z0-9_]*\s*[:=]\s*)([^\s,;]+)"
        ),
        r"\1[REDACTED]",
    ),
    RedactionRule(
        "email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[REDACTED:EMAIL]"
    ),
)


def sanitize_log(raw: str) -> tuple[str, dict[str, int]]:
    text = ANSI_ESCAPE.sub("", raw)
    text = "\n".join(TIMESTAMP_PREFIX.sub("", line).rstrip() for line in text.splitlines())
    counts: dict[str, int] = {}
    for rule in REDACTION_RULES:
        text, count = rule.pattern.subn(rule.replacement, text)
        if count:
            counts[rule.name] = count
    return text, counts
