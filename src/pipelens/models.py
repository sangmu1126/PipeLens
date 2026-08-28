from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


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


class FeedbackAccuracy(StrEnum):
    ACCURATE = "accurate"
    PARTIAL = "partial"
    INACCURATE = "inaccurate"


class TrustLevel(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED_FORK = "untrusted_fork"


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
    notes: list[str] = Field(default_factory=list)


class ChangedFile(BaseModel):
    filename: str
    status: str
    patch: str | None = None
    previous_filename: str | None = None


class RepositoryContext(BaseModel):
    changed_files: list[ChangedFile] = Field(default_factory=list)
    workflow_path: str | None = None
    workflow_content: str | None = None
    pull_request_number: int | None = None
    trust_level: TrustLevel = TrustLevel.TRUSTED
    baseline_sha: str | None = None


class RelatedFile(BaseModel):
    filename: str
    score: float = Field(ge=0, le=1)
    reasons: list[str]
    patch_excerpt: str | None = None


class FeedbackRequest(BaseModel):
    accuracy: FeedbackAccuracy | None = None
    suggestion_resolved: bool | None = None
    comment: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def require_feedback_value(self) -> "FeedbackRequest":
        if self.accuracy is None and self.suggestion_resolved is None:
            raise ValueError("accuracy or suggestion_resolved is required")
        return self


class FeedbackRecord(FeedbackRequest):
    run_id: int
    created_at: datetime
    updated_at: datetime


class AnalysisRecord(BaseModel):
    run_id: int
    delivery_id: str
    repository: str
    workflow_name: str
    head_sha: str
    html_url: str
    installation_id: int | None = None
    trust_level: TrustLevel = TrustLevel.TRUSTED
    baseline_sha: str | None = None
    status: AnalysisStatus = AnalysisStatus.QUEUED
    classification: Classification | None = None
    diagnosis: Diagnosis | None = None
    related_files: list[RelatedFile] = Field(default_factory=list)
    workflow_path: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    feedback: FeedbackRecord | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AnalysisRequest(BaseModel):
    run_id: int
    repository: str
    installation_id: int
    head_sha: str


class GitHubUser(BaseModel):
    github_user_id: int
    login: str
    avatar_url: str | None = None


class GitHubInstallation(BaseModel):
    installation_id: int
    account_login: str
    account_type: str
    repository_selection: str


class CurrentUser(GitHubUser):
    installations: list[GitHubInstallation] = Field(default_factory=list)
