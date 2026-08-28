from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PIPELENS_", extra="ignore")

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
    session_cookie_secure: bool = False
    session_ttl_days: int = 7
    database_path: str = "./pipelens.db"
    database_url: str | None = None
    publish_checks: bool = False
    max_log_bytes: int = 10 * 1024 * 1024
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

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
