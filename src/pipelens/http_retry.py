import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime

import httpx

Sleep = Callable[[float], Awaitable[None]]
RetryObserver = Callable[[str, int, float], None]

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_ACTION_REQUIRED_RATE_LIMIT_CODES = frozenset(
    {"billing_hard_limit_reached", "billing_not_active", "insufficient_quota"}
)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    jitter_ratio: float = 0.25

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    policy: RetryPolicy,
    retry_rate_limited_403: bool = False,
    on_retry: RetryObserver | None = None,
    sleep: Sleep = asyncio.sleep,
    **kwargs: object,
) -> httpx.Response:
    method = method.upper()
    for attempt in range(1, policy.max_attempts + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError:
            if attempt == policy.max_attempts or method not in _IDEMPOTENT_METHODS:
                raise
            delay = _backoff_delay(policy, attempt)
            _observe(on_retry, "transport", attempt, delay)
            await sleep(delay)
            continue

        reason = _retry_reason(response, retry_rate_limited_403)
        if reason is None or attempt == policy.max_attempts:
            return response
        delay = _response_delay(response, policy, attempt)
        if delay is None:
            return response
        _observe(on_retry, reason, attempt, delay)
        await sleep(delay)

    raise AssertionError("retry loop exited unexpectedly")


def _retry_reason(response: httpx.Response, retry_rate_limited_403: bool) -> str | None:
    if response.status_code in _TRANSIENT_STATUS_CODES:
        if response.status_code == 429 and _requires_user_action(response):
            return None
        return "rate_limit" if response.status_code == 429 else "server"
    if response.status_code == 403 and retry_rate_limited_403 and _is_rate_limited(response):
        return "rate_limit"
    return None


def _requires_user_action(response: httpx.Response) -> bool:
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return False
    return error.get("code") in _ACTION_REQUIRED_RATE_LIMIT_CODES


def _is_rate_limited(response: httpx.Response) -> bool:
    if "retry-after" in response.headers or response.headers.get("x-ratelimit-remaining") == "0":
        return True
    body = response.text.casefold()
    return "secondary rate limit" in body or "rate limit exceeded" in body


def _response_delay(
    response: httpx.Response, policy: RetryPolicy, attempt: int
) -> float | None:
    header_delay = _retry_after_delay(response)
    if header_delay is not None:
        if header_delay > policy.max_delay_seconds:
            return None
        jitter = random.uniform(0, policy.base_delay_seconds * policy.jitter_ratio)
        return min(header_delay + jitter, policy.max_delay_seconds)
    if response.status_code == 403:
        return 60.0 if policy.max_delay_seconds >= 60 else None
    return _backoff_delay(policy, attempt)


def _retry_after_delay(response: httpx.Response) -> float | None:
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                return max(0.0, retry_at.timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                pass
    if response.headers.get("x-ratelimit-remaining") == "0":
        try:
            return max(0.0, float(response.headers["x-ratelimit-reset"]) - time.time())
        except (KeyError, ValueError, OverflowError):
            return None
    return None


def _backoff_delay(policy: RetryPolicy, attempt: int) -> float:
    delay = min(policy.base_delay_seconds * (2 ** (attempt - 1)), policy.max_delay_seconds)
    if delay and policy.jitter_ratio:
        delay *= 1 + random.uniform(0, policy.jitter_ratio)
    return min(delay, policy.max_delay_seconds)


def _observe(observer: RetryObserver | None, reason: str, attempt: int, delay: float) -> None:
    if observer:
        observer(reason, attempt, delay)
