from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from crosscheck.adapters import (
    AdapterHTTPError,
    AdapterRegistry,
    AdapterRetryableError,
    AdapterResult,
    DeterministicAdapter,
    RetryPolicy,
    call_with_retries,
)
from crosscheck.config import Settings
from crosscheck.limits import SlidingWindowRateLimiter, client_identity
from crosscheck.main import create_app


class FlakyAdapter:
    provider = "mock"

    def __init__(self, failures: int = 0, *, delay: float = 0.0) -> None:
        self.failures = failures
        self.calls = 0
        self.delay = delay

    async def generate(self, prompt: str, *, model: str, deadline: float | None = None, **kwargs):
        del prompt, deadline, kwargs
        self.calls += 1
        if self.delay:
            import asyncio

            await asyncio.sleep(self.delay)
        if self.calls <= self.failures:
            raise AdapterRetryableError("transient test failure")
        return AdapterResult(
            raw_text=json.dumps(
                {
                    "answer": "ok",
                    "reasoning": "test",
                    "claims": [{"claim": "ok", "type": "fact", "confidence": 0.8}],
                    "constraints_check": {},
                }
            ),
            provider=self.provider,
            model=model,
        )


@pytest.mark.asyncio
async def test_retry_runner_is_bounded_and_honors_retry_after():
    adapter = FlakyAdapter(failures=2)
    sleeps: list[float] = []

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    result = await call_with_retries(
        adapter,
        "prompt",
        model="mock",
        deadline=time.monotonic() + 10_000,
        policy=RetryPolicy(
            attempt_timeout_seconds=10,
            max_retries=2,
            backoff_base_seconds=1,
            backoff_max_seconds=3,
            jitter_seconds=0,
            retry_after_max_seconds=2,
        ),
        sleeper=fake_sleep,
        random_fn=lambda: 0,
    )
    assert result.retry_count == 2
    assert adapter.calls == 3
    assert sleeps == [1, 2]

    class RateLimited(FlakyAdapter):
        async def generate(self, prompt: str, *, model: str, deadline=None, **kwargs):
            del prompt, model, deadline, kwargs
            self.calls += 1
            raise AdapterHTTPError(429, retry_after=100)

    with pytest.raises(Exception) as raised:
        await call_with_retries(
            RateLimited(),
            "prompt",
            model="mock",
            deadline=time.monotonic() + 10_000,
            policy=RetryPolicy(jitter_seconds=0, retry_after_max_seconds=2),
            sleeper=fake_sleep,
            random_fn=lambda: 0,
        )
    assert getattr(raised.value, "retry_count", None) == 2
    assert max(sleeps) <= 5


@pytest.mark.asyncio
async def test_http_partial_report_and_all_failures_are_not_durable(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'resilience.db'}",
        crosscheck_models="good,bad",
        adapter_max_retries=0,
    )
    good = FlakyAdapter()

    class Bad(FlakyAdapter):
        async def generate(self, prompt: str, *, model: str, deadline=None, **kwargs):
            del prompt, model, deadline, kwargs
            raise AdapterRetryableError("sensitive=secret")

    app = create_app(settings=settings, adapters=AdapterRegistry({"good": good, "bad": Bad()}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", json={"question": "Who?"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        assert any(item["model"] == "bad" and item["provider_status"] == "unavailable" for item in body["model_comparison"])
        assert "secret" not in response.text

    all_bad = AdapterRegistry({"bad": Bad()})
    settings_all_bad = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'all-bad.db'}",
        crosscheck_models="bad",
        adapter_max_retries=0,
    )
    app = create_app(settings=settings_all_bad, adapters=all_bad)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", json={"question": "Who?"})
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "NO_USABLE_MODEL_ANSWER"


@pytest.mark.asyncio
async def test_payload_rate_limit_and_trusted_proxy_boundaries(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'limits.db'}",
        crosscheck_models="deterministic",
        max_body_bytes=80,
        rate_limit_requests=1,
        rate_limit_window_seconds=60,
        max_concurrent_queries=1,
    )
    app = create_app(settings=settings, adapters=AdapterRegistry({"deterministic": DeterministicAdapter()}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        oversized = await client.post("/api/query", content=json.dumps({"question": "x" * 200}))
        assert oversized.status_code == 422
        assert oversized.json()["error"]["code"] == "VALIDATION_ERROR"
        ok = await client.post("/api/query", json={"question": "Who?"})
        assert ok.status_code == 200
        limited = await client.post("/api/query", json={"question": "Who again?"})
        assert limited.status_code == 429
        assert limited.headers.get("retry-after")
        assert limited.json()["request_id"]

    assert client_identity(
        peer="10.0.0.1",
        forwarded_for="198.51.100.2",
        trusted_proxies=["10.0.0.1"],
    ) == "198.51.100.2"
    assert client_identity(
        peer="203.0.113.9",
        forwarded_for="198.51.100.2",
        trusted_proxies=["10.0.0.1"],
    ) == "203.0.113.9"


@pytest.mark.asyncio
async def test_rate_limiter_fake_clock_window():
    now = [0.0]
    limiter = SlidingWindowRateLimiter(1, 10, clock=lambda: now[0])
    assert (await limiter.check("client")).allowed
    blocked = await limiter.check("client")
    assert not blocked.allowed and blocked.retry_after_seconds == 10
    now[0] = 10.1
    assert (await limiter.check("client")).allowed
