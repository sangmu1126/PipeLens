from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class Metrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.webhooks = Counter(
            "pipelens_webhooks_total",
            "GitHub webhooks by processing outcome.",
            ("outcome",),
            registry=self.registry,
        )
        self.analyses = Counter(
            "pipelens_analyses_total",
            "Analysis runs by terminal status.",
            ("status",),
            registry=self.registry,
        )
        self.analysis_duration = Histogram(
            "pipelens_analysis_duration_seconds",
            "End-to-end analysis duration.",
            registry=self.registry,
        )
        self.error_categories = Counter(
            "pipelens_error_categories_total",
            "Classified failures by category.",
            ("category",),
            registry=self.registry,
        )
        self.analysis_trust = Counter(
            "pipelens_analysis_trust_total",
            "Analyzed workflow runs by trust level.",
            ("level",),
            registry=self.registry,
        )
        self.redactions = Counter(
            "pipelens_redactions_total",
            "Sensitive values removed before analysis.",
            ("kind",),
            registry=self.registry,
        )
        self.log_chunks = Counter(
            "pipelens_log_chunks_total",
            "Log chunks by preprocessing outcome.",
            ("kind",),
            registry=self.registry,
        )
        self.llm_requests = Counter(
            "pipelens_llm_requests_total",
            "LLM requests by model and outcome.",
            ("model", "status"),
            registry=self.registry,
        )
        self.llm_duration = Histogram(
            "pipelens_llm_duration_seconds",
            "LLM request duration by model.",
            ("model",),
            registry=self.registry,
        )
        self.llm_tokens = Counter(
            "pipelens_llm_tokens_total",
            "LLM token usage by model and direction.",
            ("model", "direction"),
            registry=self.registry,
        )
        self.llm_estimated_cost = Counter(
            "pipelens_llm_estimated_cost_usd_total",
            "Configured estimated LLM cost in US dollars.",
            ("model",),
            registry=self.registry,
        )
        self.queue_depth = Gauge(
            "pipelens_analysis_queue_depth",
            "Number of analyses waiting in the in-process queue.",
            registry=self.registry,
        )
        self.queue_retries = Counter(
            "pipelens_queue_retries_total",
            "Analysis jobs returned to the queue after a failed attempt.",
            registry=self.registry,
        )
        self.queue_recovered = Counter(
            "pipelens_queue_recovered_total",
            "Orphaned processing jobs restored when a worker starts.",
            registry=self.registry,
        )
        self.feedback = Counter(
            "pipelens_feedback_total",
            "Submitted user feedback by dimension and value.",
            ("dimension", "value"),
            registry=self.registry,
        )

    def record_redactions(self, counts: dict[str, int]) -> None:
        for kind, count in counts.items():
            self.redactions.labels(kind=kind).inc(count)

    def record_llm(
        self,
        model: str,
        status: str,
        duration: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost: float = 0,
    ) -> None:
        self.llm_requests.labels(model=model, status=status).inc()
        self.llm_duration.labels(model=model).observe(duration)
        self.llm_tokens.labels(model=model, direction="input").inc(input_tokens)
        self.llm_tokens.labels(model=model, direction="output").inc(output_tokens)
        self.llm_estimated_cost.labels(model=model).inc(estimated_cost)
