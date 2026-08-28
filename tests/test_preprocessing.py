from pipelens.preprocessing import iter_text_chunks, preprocess_log


def test_text_chunking_preserves_content_and_bounds_chunks() -> None:
    text = "short line\n" + "x" * 2_500 + "\nlast line"
    chunks = list(iter_text_chunks(text, 1_000))

    assert "".join(chunks) == text
    assert all(len(chunk) <= 1_000 for chunk in chunks)


def test_preprocessing_redacts_each_chunk_and_keeps_early_errors() -> None:
    raw = (
        "setup\n"
        "npm ERR! ERESOLVE unable to resolve dependency tree\n"
        + "noise\n" * 300
        + "Authorization: Bearer secret-token\n"
        + "fatal: no space left on device\n"
    )

    result = preprocess_log(raw, chunk_chars=1_000, context_lines=2, max_error_chunks=10)

    assert result.chunks_processed > 1
    assert "ERESOLVE" in result.context
    assert "no space left on device" in result.context
    assert "secret-token" not in result.context
    assert result.redactions["authorization"] == 1
