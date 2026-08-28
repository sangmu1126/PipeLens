from dataclasses import dataclass

from pipelens.config import Settings
from pipelens.github import GitHubClient
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
    github = GitHubClient(
        settings.github_app_id, settings.github_private_key, settings.max_log_bytes
    )
    metrics = Metrics()
    llm_provider: LLMProvider | None = None
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("PIPELENS_OPENAI_API_KEY is required for the OpenAI provider")
        llm_provider = OpenAIResponsesProvider(
            settings.openai_api_key, settings.openai_model, settings.max_llm_input_chars
        )
    elif settings.llm_provider != "none":
        raise ValueError(f"unsupported LLM provider: {settings.llm_provider}")
    pipeline = AnalysisPipeline(settings, store, github, llm_provider, metrics)
    queue = create_queue(settings.queue_backend, settings.redis_url, settings.queue_name)
    return Runtime(store, github, llm_provider, metrics, pipeline, queue)
