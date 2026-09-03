from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from crosscheck.adapters import AdapterRegistry, DeterministicAdapter
from crosscheck.config import Settings
from crosscheck.contracts import AdapterResult, Claim, QueryRequest, QuestionSummary, ReportResponse, VerificationResult
from crosscheck.main import create_app
from crosscheck.query import QueryService
from crosscheck.verifier_registry import default_verifier_registry
from crosscheck.verifiers import CodeVerifier, FactVerifier, StaticVerifier, VerifierRegistry


@pytest.mark.asyncio
async def test_missing_fact_search_key_is_unavailable_not_unverified() -> None:
    verifier = default_verifier_registry(Settings(tavily_api_key=None)).get("fact")

    result = await verifier.verify(
        Claim(claim="Paris is the capital of France", type="fact", confidence=0.8),
        question="q",
        constraints=None,
    )

    assert result.status == "unavailable"
    assert result.failure_class == "configuration_unavailable"
    assert result.details == {"reason": "fact search is not configured"}


@pytest.mark.asyncio
async def test_fact_verifier_retains_recency_and_reports_credible_conflict() -> None:
    def search(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.gov/current",
                        "title": "Paris is not the capital of France",
                        "content": "Paris is not the capital of France.",
                        "published_date": "2026-08-01",
                        "relation": "conflicting",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(search)) as client:
        result = await FactVerifier("secret", http_client=client).verify(
            Claim(claim="Paris is the capital of France", type="fact", confidence=0.8),
            question="q",
            constraints=None,
        )

    assert result.status == "conflict"
    assert result.evidence[0]["relation"] == "conflicting"
    assert result.evidence[0]["publication_date"] == "2026-08-01"
    assert 0.0 <= result.evidence[0]["recency"] <= 1.0
    assert result.details["conflict_count"] == 1


@pytest.mark.asyncio
async def test_missing_docker_image_is_sanitized_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon_error = "docker: Error response from daemon: No such image: private.registry/internal:secret"
    monkeypatch.setattr(
        CodeVerifier,
        "_run_bounded",
        staticmethod(
            lambda command, script, **kwargs: SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=daemon_error,
                output_truncated=False,
                timed_out=False,
            )
        ),
    )

    result = await CodeVerifier("missing-image").verify(
        Claim(claim="```python\ndef add(a, b): return a + b\n```", type="code", confidence=0.9),
        question="```python\nassert add(1, 2) == 3\n```",
        constraints=None,
    )

    assert result.status == "unavailable"
    assert result.failure_class == "sandbox_unavailable"
    assert result.details == {"reason": "sandbox image or Docker service unavailable"}
    assert daemon_error not in str(result.model_dump())


@pytest.mark.asyncio
async def test_constraint_service_failure_makes_report_partial(tmp_path) -> None:
    class FailingConstraints:
        version = "failing-test"

        async def check(self, request, answers, *, deadline=None):
            raise RuntimeError("constraint backend failed")

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'constraints.db'}",
        redis_url="",
        crosscheck_models="deterministic",
    )
    app = create_app(
        settings=settings,
        adapters=AdapterRegistry({"deterministic": DeterministicAdapter()}),
        verifiers=VerifierRegistry({"*": StaticVerifier(VerificationResult(status="verified", confidence=1.0))}),
        constraint_service=FailingConstraints(),
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", json={"question": "Pick one", "constraints": {"weight": "2 kg"}})

    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert "constraint verification was unavailable" in response.json()["warnings"]


@pytest.mark.asyncio
async def test_single_flight_lock_miss_waits_beyond_250ms_for_cached_report() -> None:
    cached_report = ReportResponse(
        report_id=uuid4(),
        status="complete",
        created_at=datetime.now(timezone.utc),
        duration_ms=1,
        question=QuestionSummary(
            id=uuid4(),
            text="q",
            question_type="fact",
            question_type_origin="fallback",
            models=["m"],
        ),
        recommendation_message="cached",
    )

    class ContendedCache:
        def __init__(self) -> None:
            self.get_calls = 0

        async def get(self, key: str):
            self.get_calls += 1
            return cached_report if self.get_calls >= 7 else None

        async def acquire_lock(self, key: str):
            return None

        async def set(self, key: str, report: ReportResponse) -> None:
            raise AssertionError("a contender must not write a duplicate report")

        async def release_lock(self, key: str, token: str) -> None:
            raise AssertionError("a contender does not own the lock")

        def warnings(self) -> list[str]:
            return []

    class Provider:
        provider = "p"

        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, prompt: str, *, model: str, deadline: float | None = None, **kwargs):
            self.calls += 1
            return AdapterResult(raw_text='{"answer":"duplicate","claims":[],"constraints_check":{}}', provider="p", model=model)

    async def no_wait(_: float) -> None:
        return None

    provider = Provider()
    service = QueryService(
        settings=Settings(crosscheck_models="m", redis_url="", query_deadline_seconds=2),
        store=SimpleNamespace(),
        adapters=AdapterRegistry({"m": provider}),
        cache=ContendedCache(),
        sleeper=no_wait,
    )

    result = await service.execute(QueryRequest(question="q"))

    assert result.cached is True
    assert result.report_id == cached_report.report_id
    assert provider.calls == 0
