import base64
import hashlib
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PIPELENS_", extra="ignore")

    environment: Literal["development", "production"] = "development"
    webhook_secret: str = "development-secret"
    github_app_id: str | None = None
    github_private_key: str | None = None
    github_app_slug: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    public_url: str = "http://localhost:3000"
    auth_required: bool = True
    session_secret: str = "development-session-secret"
    token_encryption_key: str | None = None
    token_encryption_fallback_keys: str = ""
    session_cookie_secure: bool = False
    session_ttl_days: int = 7
    database_path: str = "./pipelens.db"
    database_url: str | None = None
    publish_checks: bool = False
    max_log_bytes: int = 10 * 1024 * 1024
    log_chunk_chars: int = 200_000
    max_error_chunks: int = 10
    error_context_lines: int = 8
    llm_provider: str = "none"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6"
    max_llm_input_chars: int = 30_000
    llm_input_cost_per_million: float = 0
    llm_output_cost_per_million: float = 0
    queue_backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "pipelens:analyses"
    worker_max_attempts: int = 3
    worker_metrics_port: int = 8001
    worker_lease_seconds: int = 60
    worker_heartbeat_seconds: float = 15
    http_retry_max_attempts: int = 3
    http_retry_base_seconds: float = 1.0
    http_retry_max_seconds: float = 60.0
    analysis_start_slo_seconds: float = 60.0
    analysis_completion_slo_seconds: float = 120.0

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.database_path}"

    @property
    def token_encryption_key_ring(self) -> list[str]:
        primary = self.token_encryption_key or base64.urlsafe_b64encode(
            hashlib.sha256(self.session_secret.encode()).digest()
        ).decode()
        keys = [primary]
        keys.extend(
            key.strip()
            for key in self.token_encryption_fallback_keys.split(",")
            if key.strip()
        )
        return list(dict.fromkeys(keys))

    @model_validator(mode="after")
    def validate_worker_lease(self) -> "Settings":
        if self.worker_lease_seconds < 1:
            raise ValueError("worker lease must be at least one second")
        if not 0 < self.worker_heartbeat_seconds < self.worker_lease_seconds:
            raise ValueError("worker heartbeat must be positive and shorter than the lease")
        if self.analysis_start_slo_seconds <= 0 or self.analysis_completion_slo_seconds <= 0:
            raise ValueError("analysis SLO thresholds must be positive")
        if self.environment == "production":
            public_url = urlparse(self.public_url)
            if public_url.scheme != "https" or not public_url.netloc:
                raise ValueError("production public URL must use HTTPS")
            if not self.auth_required:
                raise ValueError("production authentication must be required")
            if not self.session_cookie_secure:
                raise ValueError("production session cookies must be secure")
            if len(self.webhook_secret) < 32:
                raise ValueError("production webhook secret must be at least 32 characters")
            if len(self.session_secret) < 32:
                raise ValueError("production session secret must be at least 32 characters")
            if not self.token_encryption_key:
                raise ValueError("production token encryption key must be configured")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
