import json
from enum import StrEnum
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from pipelens.models import (
    Classification,
    Diagnosis,
    ErrorCategory,
    Evidence,
    RelatedFile,
    Suggestion,
)

PROMPT_VERSION = "diagnosis-v1"


class LLMError(RuntimeError):
    pass


class EvidenceSource(StrEnum):
    LOG = "log"
    WORKFLOW = "workflow"
    DIFF = "diff"


class LLMEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: EvidenceSource
    content: str
    location: str | None


class LLMSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    file: str | None
    patch: str | None


class LLMAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ErrorCategory
    summary: str
    root_cause: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[LLMEvidence]
    suggestions: list[LLMSuggestion]


class LLMContext(BaseModel):
    classification: Classification
    log: str
    related_files: list[RelatedFile]
    workflow_path: str | None = None
    workflow_content: str | None = None


class LLMProviderResult(BaseModel):
    analysis: LLMAnalysis
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(Protocol):
    model_name: str

    async def analyze(self, context: LLMContext) -> LLMProviderResult: ...


class OpenAIResponsesProvider:
    api_url = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        api_key: str,
        model_name: str,
        max_input_chars: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.max_input_chars = max_input_chars
        self.transport = transport

    async def analyze(self, context: LLMContext) -> LLMProviderResult:
        input_json = _bounded_context_json(context, self.max_input_chars)
        payload = {
            "model": self.model_name,
            "input": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": input_json},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "pipelens_diagnosis",
                    "strict": True,
                    "schema": LLMAnalysis.model_json_schema(),
                }
            },
        }
        async with httpx.AsyncClient(timeout=60, transport=self.transport) as client:
            response = await client.post(
                self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if response.is_error:
            raise LLMError(f"OpenAI Responses API returned HTTP {response.status_code}")
        body = response.json()
        if body.get("status") == "incomplete":
            raise LLMError("OpenAI response was incomplete")
        output_text = _response_output_text(body)
        try:
            analysis = LLMAnalysis.model_validate_json(output_text)
        except ValueError as exc:
            raise LLMError("OpenAI response did not match the diagnosis schema") from exc
        usage = body.get("usage") or {}
        return LLMProviderResult(
            analysis=analysis,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )


def validate_llm_analysis(result: LLMAnalysis, context: LLMContext) -> Diagnosis:
    valid_evidence: list[Evidence] = []
    for item in result.evidence:
        source_text = _evidence_source_text(item.source, context)
        if item.content and item.content in source_text:
            valid_evidence.append(
                Evidence(source=item.source.value, content=item.content, location=item.location)
            )
    if not valid_evidence:
        raise LLMError("LLM diagnosis has no evidence grounded in the supplied context")

    allowed_files = {item.filename for item in context.related_files}
    if context.workflow_path:
        allowed_files.add(context.workflow_path)
    suggestions = [
        Suggestion(description=item.description, file=item.file, patch=item.patch)
        for item in result.suggestions
        if item.file is None or item.file in allowed_files
    ]
    conflicts: list[str] = []
    confidence = result.confidence
    if result.category != context.classification.category:
        conflicts.append(
            "규칙 기반 분류 "
            f"({context.classification.category.value})와 LLM 분류 "
            f"({result.category.value})가 다릅니다."
        )
        confidence = min(confidence, context.classification.confidence)

    return Diagnosis(
        summary=result.summary,
        root_cause=result.root_cause,
        confidence=confidence,
        evidence=valid_evidence,
        suggestions=suggestions,
        conflicts=conflicts,
    )


def _system_prompt() -> str:
    return (
        "You diagnose GitHub Actions failures. Use only the supplied sanitized log, workflow, "
        "and diff excerpts. Every claimed cause must have verbatim evidence in those inputs. "
        "Never invent file paths. If evidence is insufficient, set root_cause to '확인 불가' and "
        "use low confidence. Return Korean prose in the required JSON schema."
    )


def _bounded_context_json(context: LLMContext, limit: int) -> str:
    data = context.model_dump(mode="json")
    encoded = json.dumps(data, ensure_ascii=False)
    if len(encoded) <= limit:
        return encoded

    data["log"] = data["log"][: max(500, limit // 2)]
    if data.get("workflow_content"):
        data["workflow_content"] = data["workflow_content"][: max(250, limit // 5)]
    for related in data["related_files"]:
        if related.get("patch_excerpt"):
            related["patch_excerpt"] = related["patch_excerpt"][:500]
    encoded = json.dumps(data, ensure_ascii=False)
    while len(encoded) > limit and data["related_files"]:
        data["related_files"].pop()
        encoded = json.dumps(data, ensure_ascii=False)
    while len(encoded) > limit and (data["log"] or data.get("workflow_content")):
        data["log"] = data["log"][: len(data["log"]) // 2]
        workflow = data.get("workflow_content") or ""
        data["workflow_content"] = workflow[: len(workflow) // 2] or None
        encoded = json.dumps(data, ensure_ascii=False)
    if len(encoded) > limit:
        raise LLMError("configured LLM input limit is too small for the diagnosis metadata")
    return encoded


def _response_output_text(body: dict) -> str:
    for output in body.get("output", []):
        if output.get("type") != "message":
            continue
        for content in output.get("content", []):
            if content.get("type") == "refusal":
                raise LLMError("OpenAI model refused the diagnosis request")
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    raise LLMError("OpenAI response contained no output text")


def _evidence_source_text(source: EvidenceSource, context: LLMContext) -> str:
    if source is EvidenceSource.LOG:
        return context.log
    if source is EvidenceSource.WORKFLOW:
        return context.workflow_content or ""
    return "\n".join(item.patch_excerpt or "" for item in context.related_files)
