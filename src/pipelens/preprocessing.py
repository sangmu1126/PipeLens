from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from pipelens.classifier import extract_error_context, has_error_signal
from pipelens.sanitizer import sanitize_log


@dataclass(frozen=True)
class PreprocessedLog:
    context: str
    redactions: dict[str, int]
    chunks_processed: int
    error_chunks: int


def preprocess_log(
    raw: str,
    chunk_chars: int,
    context_lines: int,
    max_error_chunks: int,
) -> PreprocessedLog:
    return preprocess_logs(
        [raw],
        chunk_chars=chunk_chars,
        context_lines=context_lines,
        max_error_chunks=max_error_chunks,
    )


def preprocess_logs(
    raw_logs: Iterable[str],
    chunk_chars: int,
    context_lines: int,
    max_error_chunks: int,
) -> PreprocessedLog:
    contexts: list[str] = []
    fallback = ""
    redactions: dict[str, int] = {}
    chunks_processed = 0
    error_chunks = 0
    for raw in raw_logs:
        for chunk in iter_text_chunks(raw, max(1_000, chunk_chars)):
            chunks_processed += 1
            sanitized, counts = sanitize_log(chunk)
            for kind, count in counts.items():
                redactions[kind] = redactions.get(kind, 0) + count
            fallback = sanitized
            if has_error_signal(sanitized) and error_chunks < max(1, max_error_chunks):
                contexts.append(
                    extract_error_context(sanitized, context_lines, max_sections=2)
                )
                error_chunks += 1
    context = "\n...\n".join(contexts)
    if not context:
        context = extract_error_context(fallback, context_lines) if fallback else ""
    return PreprocessedLog(context, redactions, chunks_processed, error_chunks)


def iter_text_chunks(text: str, max_chars: int) -> Iterator[str]:
    if not text:
        return
    buffered: list[str] = []
    buffered_chars = 0
    for line in text.splitlines(keepends=True):
        while len(line) > max_chars:
            if buffered:
                yield "".join(buffered)
                buffered, buffered_chars = [], 0
            yield line[:max_chars]
            line = line[max_chars:]
        if buffered and buffered_chars + len(line) > max_chars:
            yield "".join(buffered)
            buffered, buffered_chars = [], 0
        buffered.append(line)
        buffered_chars += len(line)
    if buffered:
        yield "".join(buffered)
