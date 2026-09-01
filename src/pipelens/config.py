import base64
import hashlib
import os
import stat
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MAX_SECRET_FILE_BYTES = 1024 * 1024


def _read_secret_file(path: Path, setting_name: str) -> str:
    try:
        path_stat = path.stat()
        if not stat.S_ISREG(path_stat.st_mode):
            raise ValueError(f"{setting_name} must reference a regular file")
        with path.open("rb") as handle:
            file_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError(f"{setting_name} must reference a regular file")
            content = handle.read(_MAX_SECRET_FILE_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"{setting_name} must reference a readable file") from exc

    if len(content) > _MAX_SECRET_FILE_BYTES:
        raise ValueError(f"{setting_name} must not exceed {_MAX_SECRET_FILE_BYTES} bytes")
    try:
        value = content.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{setting_name} must contain UTF-8 text") from exc
    if not value:
        raise ValueError(f"{setting_name} must not be empty")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PIPELENS_", extra="ignore")

    secret_file_fields: ClassVar[dict[str, str]] = {
        "webhook_secret": "webhook_secret_file",
        "github_private_key": "github_private_key_file",
        "github_client_secret": "github_client_secret_file",
        "session_secret": "session_secret_file",
        "token_encryption_key": "token_encryption_key_file",
        "token_encryption_fallback_keys": "token_encryption_fallback_keys_file",
        "openai_api_key": "openai_api_key_file",
        "database_url": "database_url_file",
        "redis_url": "redis_url_file",
    }
    production_github_settings: ClassVar[tuple[str, ...]] = (
        "github_app_id",
        "github_private_key",
        "github_app_slug",
        "github_client_id",
        "github_client_secret",
    )

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

    webhook_secret_file: Path | None = None
    github_private_key_file: Path | None = None
    github_client_secret_file: Path | None = None
    session_secret_file: Path | None = None
    token_encryption_key_file: Path | None = None
    token_encryption_fallback_keys_file: Path | None = None
    openai_api_key_file: Path | None = None
    database_url_file: Path | None = None
    redis_url_file: Path | None = None

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
    def resolve_secrets_and_validate(self) -> "Settings":
        for value_name, file_name in self.secret_file_fields.items():
            secret_file = getattr(self, file_name)
            if secret_file is None:
                continue
            direct_value = getattr(self, value_name)
            if value_name in self.model_fields_set and direct_value not in (None, ""):
                raise ValueError(
                    f"PIPELENS_{value_name.upper()} and PIPELENS_{file_name.upper()} conflict"
                )
            setattr(
                self,
                value_name,
                _read_secret_file(secret_file, f"PIPELENS_{file_name.upper()}"),
            )

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
            if public_url.username or public_url.password:
                raise ValueError("production public URL must not contain credentials")
            if public_url.path not in ("", "/") or public_url.params or public_url.query:
                raise ValueError("production public URL must be an origin without path or query")
            if public_url.fragment:
                raise ValueError("production public URL must not contain a fragment")
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
            missing_github_settings = [
                f"PIPELENS_{name.upper()}"
                for name in self.production_github_settings
                if not isinstance(getattr(self, name), str) or not getattr(self, name).strip()
            ]
            if missing_github_settings:
                raise ValueError(
                    "production GitHub App settings must be configured: "
                    + ", ".join(missing_github_settings)
                )
            if not self.github_app_id.isdigit() or int(self.github_app_id) < 1:
                raise ValueError("production GitHub App ID must be a positive integer")
            if not self.database_url:
                raise ValueError("production PostgreSQL URL must be configured")
            database_url = urlparse(self.database_url)
            if database_url.scheme != "postgresql+psycopg" or not database_url.netloc:
                raise ValueError("production database URL must use postgresql+psycopg")
            if self.queue_backend != "redis":
                raise ValueError("production queue backend must be redis")
            redis_url = urlparse(self.redis_url)
            if redis_url.scheme not in ("redis", "rediss") or not redis_url.netloc:
                raise ValueError("production Redis URL must use redis or rediss")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
