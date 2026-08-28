from prometheus_client import generate_latest

from pipelens.metrics import Metrics


def test_metrics_record_redactions_and_llm_usage() -> None:
    metrics = Metrics()

    metrics.record_redactions({"github_token": 2, "email": 1})
    metrics.record_llm(
        model="test-model",
        status="success",
        duration=0.25,
        input_tokens=100,
        output_tokens=20,
        estimated_cost=0.001,
    )
    metrics.http_retries.labels(provider="github", reason="rate_limit").inc()
    output = generate_latest(metrics.registry).decode()

    assert 'pipelens_redactions_total{kind="github_token"} 2.0' in output
    assert 'pipelens_redactions_total{kind="email"} 1.0' in output
    assert 'pipelens_llm_requests_total{model="test-model",status="success"} 1.0' in output
    assert 'pipelens_llm_tokens_total{direction="input",model="test-model"} 100.0' in output
    assert 'pipelens_llm_tokens_total{direction="output",model="test-model"} 20.0' in output
    assert 'pipelens_llm_estimated_cost_usd_total{model="test-model"} 0.001' in output
    assert (
        'pipelens_http_retries_total{provider="github",reason="rate_limit"} 1.0' in output
    )
