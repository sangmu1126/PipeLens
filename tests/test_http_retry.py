import httpx
import pytest

from pipelens.http_retry import RetryPolicy, request_with_retry


def _policy(max_attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=max_attempts,
        base_delay_seconds=0.5,
        max_delay_seconds=10,
        jitter_ratio=0,
    )


@pytest.mark.asyncio
async def test_retries_transient_status_with_exponential_backoff() -> None:
    calls = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls < 3 else 200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await request_with_retry(
            client,
            "GET",
            "https://example.test",
            policy=_policy(),
            sleep=_record_sleep(delays),
        )

    assert response.status_code == 200
    assert calls == 3
    assert delays == [0.5, 1.0]


@pytest.mark.asyncio
async def test_retry_after_beyond_bound_is_not_retried_early() -> None:
    calls = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "30"})
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await request_with_retry(
            client,
            "GET",
            "https://example.test",
            policy=_policy(),
            sleep=_record_sleep(delays),
        )

    assert response.status_code == 429
    assert calls == 1
    assert delays == []


@pytest.mark.asyncio
async def test_github_rate_limited_403_is_opt_in() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            403,
            headers={"Retry-After": "0"},
            json={"message": "secondary rate limit"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await request_with_retry(
            client,
            "GET",
            "https://example.test",
            policy=_policy(max_attempts=2),
            retry_rate_limited_403=False,
            sleep=_record_sleep([]),
        )
        assert response.status_code == 403
        assert calls == 1

        await request_with_retry(
            client,
            "GET",
            "https://example.test",
            policy=_policy(max_attempts=2),
            retry_rate_limited_403=True,
            sleep=_record_sleep([]),
        )
        assert calls == 3


@pytest.mark.asyncio
async def test_transport_error_is_not_retried_for_post() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ReadTimeout):
            await request_with_retry(
                client,
                "POST",
                "https://example.test",
                policy=_policy(),
                sleep=_record_sleep([]),
            )

    assert calls == 1


@pytest.mark.asyncio
async def test_quota_error_is_not_retried() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, json={"error": {"code": "insufficient_quota"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await request_with_retry(
            client,
            "POST",
            "https://example.test",
            policy=_policy(),
            sleep=_record_sleep([]),
        )

    assert response.status_code == 429
    assert calls == 1


def _record_sleep(delays: list[float]):
    async def sleep(delay: float) -> None:
        delays.append(delay)

    return sleep
