from dataclasses import dataclass

from pipelens.config import Settings
from pipelens.github import GitHubClient
from pipelens.http_retry import RetryPolicy
from pipelens.llm import LLMProvider, OpenAIResponsesProvider
from pipelens.metrics import Metrics
from pipelens.pipeline import AnalysisPipeline
from pipelens.queue import AnalysisQueue, create_queue
from pipelens.store import AnalysisStore


@dataclass(frozen=True)
class Runtime:
    store: AnalysisStore
    github: GitHubClient
    llm_provider: LLMProvider | None
    metrics: Metrics
    pipeline: AnalysisPipeline
    queue: AnalysisQueue


def create_runtime(settings: Settings) -> Runtime:
    store = AnalysisStore(settings.resolved_database_url)
    metrics = Metrics()
    retry_policy = RetryPolicy(
        max_attempts=settings.http_retry_max_attempts,
        base_delay_seconds=settings.http_retry_base_seconds,
        max_delay_seconds=settings.http_retry_max_seconds,
    )
    github = GitHubClient(
        settings.github_app_id,
        settings.github_private_key,
        settings.max_log_bytes,
        retry_policy=retry_policy,
        on_retry=lambda reason, _attempt, _delay: metrics.http_retries.labels(
            provider="github", reason=reason
        ).inc(),
    )
    llm_provider: LLMProvider | None = None
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("PIPELENS_OPENAI_API_KEY is required for the OpenAI provider")
        llm_provider = OpenAIResponsesProvider(
            settings.openai_api_key,
            settings.openai_model,
            settings.max_llm_input_chars,
            retry_policy=retry_policy,
            on_retry=lambda reason, _attempt, _delay: metrics.http_retries.labels(
                provider="openai", reason=reason
            ).inc(),
        )
    elif settings.llm_provider != "none":
        raise ValueError(f"unsupported LLM provider: {settings.llm_provider}")
    pipeline = AnalysisPipeline(settings, store, github, llm_provider, metrics)
    queue = create_queue(settings.queue_backend, settings.redis_url, settings.queue_name)
    return Runtime(store, github, llm_provider, metrics, pipeline, queue)
