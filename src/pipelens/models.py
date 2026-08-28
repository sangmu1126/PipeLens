from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorCategory(StrEnum):
    TEST = "test_failure"
    BUILD = "build_failure"
    DEPENDENCY = "dependency_installation_failure"
    LINT = "lint_or_formatter_failure"
    DOCKER = "docker_build_failure"
    DEPLOY_AUTH = "deployment_authentication_failure"
    MISSING_ENV = "missing_environment_variable"
    TIMEOUT = "timeout"
    RESOURCE = "resource_exhaustion"
    WORKFLOW = "github_actions_workflow_error"
    UNKNOWN = "unknown"


class Evidence(BaseModel):
    source: str
    content: str
    location: str | None = None


class Classification(BaseModel):
    category: ErrorCategory
    confidence: float = Field(ge=0, le=1)
    first_error: str
    related_step: str | None = None
    matched_rules: list[str] = Field(default_factory=list)


class Suggestion(BaseModel):
    description: str
    file: str | None = None
    patch: str | None = None


class Diagnosis(BaseModel):
    summary: str
    root_cause: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence]
    suggestions: list[Suggestion] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class AnalysisRecord(BaseModel):
    run_id: int
    delivery_id: str
    repository: str
    workflow_name: str
    head_sha: str
    html_url: str
    installation_id: int | None = None
    status: AnalysisStatus = AnalysisStatus.QUEUED
    classification: Classification | None = None
    diagnosis: Diagnosis | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AnalysisRequest(BaseModel):
    run_id: int
    repository: str
    installation_id: int
    head_sha: str
