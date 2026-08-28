import json

import httpx
import pytest

from pipelens.llm import (
    LLMAnalysis,
    LLMContext,
    LLMError,
    OpenAIResponsesProvider,
    validate_llm_analysis,
)
from pipelens.models import (
    Classification,
    ErrorCategory,
    ExecutionContext,
    FailedJobContext,
    RelatedFile,
)


def _context() -> LLMContext:
    return LLMContext(
        classification=Classification(
            category=ErrorCategory.MISSING_ENV,
            confidence=0.94,
            first_error="DATABASE_URL environment variable not set",
            matched_rules=["env.missing"],
        ),
        log="KeyError: DATABASE_URL environment variable not set",
        workflow_path=".github/workflows/ci.yml",
        workflow_content="env:\n  NODE_ENV: test",
        related_files=[
            RelatedFile(
                filename="src/config.py",
                score=0.9,
                reasons=["로그에 경로 등장"],
                patch_excerpt="+database_url = os.environ['DATABASE_URL']",
            )
        ],
        execution_context=ExecutionContext(
            workflow_name="CI",
            head_branch="main",
            failed_jobs=[
                FailedJobContext(
                    name="tests", failed_steps=["Run pytest"], runner_labels=["ubuntu-latest"]
                )
            ],
        ),
    )


def _analysis(**overrides) -> LLMAnalysis:
    values = {
        "category": "missing_environment_variable",
        "summary": "환경변수 설정 누락",
        "root_cause": "DATABASE_URL이 설정되지 않았습니다.",
        "confidence": 0.91,
        "evidence": [
            {
                "source": "log",
                "content": "DATABASE_URL environment variable not set",
                "location": "tests",
            }
        ],
        "suggestions": [
            {
                "description": "Workflow에 환경변수를 전달하세요.",
                "file": ".github/workflows/ci.yml",
                "patch": None,
            }
        ],
    }
    values.update(overrides)
    return LLMAnalysis.model_validate(values)


def test_validate_llm_analysis_keeps_only_grounded_files() -> None:
    result = _analysis(
        suggestions=[
            {
                "description": "Workflow 수정",
                "file": ".github/workflows/ci.yml",
                "patch": None,
            },
            {"description": "가짜 파일 수정", "file": "missing.py", "patch": None},
        ]
    )

    diagnosis = validate_llm_analysis(result, _context())

    assert [item.file for item in diagnosis.suggestions] == [".github/workflows/ci.yml"]
    assert diagnosis.evidence[0].source == "log"


def test_validate_llm_analysis_reports_rule_conflict() -> None:
    diagnosis = validate_llm_analysis(_analysis(category="build_failure"), _context())

    assert diagnosis.conflicts
    assert "build_failure" in diagnosis.conflicts[0]


def test_validate_llm_analysis_rejects_invented_evidence() -> None:
    result = _analysis(evidence=[{"source": "log", "content": "invented output", "location": None}])

    with pytest.raises(LLMError, match="no evidence"):
        validate_llm_analysis(result, _context())


@pytest.mark.asyncio
async def test_openai_provider_requests_strict_structured_output() -> None:
    captured: dict = {}
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        captured_headers.update(request.headers)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 120, "output_tokens": 30},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": _analysis().model_dump_json()}],
                    }
                ],
            },
        )

    provider = OpenAIResponsesProvider(
        "test-key", "test-model", 30_000, transport=httpx.MockTransport(handler)
    )

    result = await provider.analyze(_context())

    assert result.analysis.category is ErrorCategory.MISSING_ENV
    assert result.input_tokens == 120
    assert result.output_tokens == 30
    assert captured["model"] == "test-model"
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True
    assert captured["store"] is False
    assert captured_headers["x-client-request-id"]
    supplied_context = json.loads(captured["input"][1]["content"])
    assert supplied_context["execution_context"]["failed_jobs"][0]["runner_labels"] == [
        "ubuntu-latest"
    ]


@pytest.mark.asyncio
async def test_openai_provider_retries_rate_limit_with_stable_request_id() -> None:
    request_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_ids.append(request.headers["x-client-request-id"])
        if len(request_ids) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": _analysis().model_dump_json()}],
                    }
                ],
            },
        )

    provider = OpenAIResponsesProvider(
        "test-key", "test-model", 30_000, transport=httpx.MockTransport(handler)
    )

    await provider.analyze(_context())

    assert len(request_ids) == 2
    assert request_ids[0] == request_ids[1]


@pytest.mark.asyncio
async def test_openai_provider_rejects_incomplete_response() -> None:
    provider = OpenAIResponsesProvider(
        "test-key",
        "test-model",
        30_000,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"status": "incomplete", "output": []})
        ),
    )

    with pytest.raises(LLMError, match="incomplete"):
        await provider.analyze(_context())
