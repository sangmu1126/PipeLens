from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PIPELENS_", extra="ignore")

    webhook_secret: str = "development-secret"
    github_app_id: str | None = None
    github_private_key: str | None = None
    database_path: str = "./pipelens.db"
    publish_checks: bool = False
    max_log_bytes: int = 10 * 1024 * 1024
    error_context_lines: int = 8
    llm_provider: str = "none"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6"
    max_llm_input_chars: int = 30_000
    llm_input_cost_per_million: float = 0
    llm_output_cost_per_million: float = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
