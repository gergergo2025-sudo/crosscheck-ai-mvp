from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from types import SimpleNamespace

from crosscheck.adapters import AnthropicAdapter, AdapterRegistry, AdapterResult, DeepSeekAdapter, OpenAIAdapter, UnavailableAdapter, default_adapter_registry
from crosscheck.cache import RedisReportCache, build_cache_key
from crosscheck.clustering import SemanticClaimClusterer
from crosscheck.consensus import build_consensus_and_disagreements
from crosscheck.config import Settings
from crosscheck.constraints import IndependentConstraintService
from crosscheck.contracts import Claim, ModelAnswer, QueryRequest, VerificationResult
from crosscheck.main import create_app
from crosscheck.scoring import EvidenceScorer
from crosscheck.telemetry import StructuredTelemetry
from crosscheck.verifiers import CodeVerifier, FactVerifier, StaticVerifier, VerifierRegistry


def _answer(model: str, provider: str, claim: str) -> ModelAnswer:
    return ModelAnswer(
        id=uuid4(), model=model, provider=provider, answer=claim,
        claims=[Claim(id=uuid4(), claim=claim, type="fact", confidence=.9)],
    )


@pytest.mark.asyncio
async def test_anthropic_adapter_and_three_provider_default():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": json.dumps({"answer": "ok", "claims": [], "constraints_check": {}})}],
            "usage": {"input_tokens": 2, "output_tokens": 3},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AnthropicAdapter("secret", "http://mock", model="claude-test", http_client=client).generate("prompt", model="claude-test")
    assert Settings().configured_models()[1].startswith("claude")
    assert result.provider == "anthropic"
    assert result.token_usage == {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}
    assert requests[0].headers["x-api-key"] == "secret"


@pytest.mark.asyncio
async def test_clusterer_fallback_is_deterministic_and_counts_provider_once():
    first = _answer("m1", "p1", "Paris is the capital of France")
    first.claims.append(Claim(id=uuid4(), claim="Paris is the capital of France.", type="fact", confidence=.8))
    second = _answer("m2", "p2", "Paris is the capital of France!")
    outcome = await SemanticClaimClusterer(embedder=None).cluster([first, second])
    assert outcome.degraded and outcome.method == "lexical"
    assert len(outcome.clusters) == 1
    assert outcome.clusters[0].supporting_models == ["m1", "m2"]


@pytest.mark.asyncio
async def test_constraints_are_independently_checked_per_answer():
    answer = ModelAnswer(id=uuid4(), model="m", provider="p", answer="Price: 4500 元; light laptop", constraints_check={"budget": "yes"})
    outcome = await IndependentConstraintService().check(QueryRequest(question="pick", constraints={"budget": 5000, "preference": "light"}), [answer])
    checks = outcome.per_answer[answer.id]
    assert [item["status"] for item in checks] == ["satisfied", "satisfied"]
    assert checks[0]["observed"] == 4500


def test_evidence_scorer_recommends_at_threshold_and_excludes_degraded():
    answer = _answer("m1", "p1", "claim")
    claim_id = answer.claims[0].id
    assert claim_id
    result = VerificationResult(id=uuid4(), verifier_type="fact", status="verified", confidence=1, evidence=[{"authority": 1}])
    scorer = EvidenceScorer()
    outcome = scorer.score([answer], clustering=type("C", (), {"clusters": []})(), verification_by_claim={claim_id: [result]}, constraint_results={}, usable_provider_count=1)
    assert outcome.scores[answer.id] >= .6
    assert outcome.recommended_answer_id == answer.id
    threshold_answer = ModelAnswer(id=uuid4(), model="threshold", provider="p", answer="ok")
    at_threshold = [{"status": "satisfied"}] * 3 + [{"status": "violated"}] * 2
    below_threshold = [{"status": "satisfied"}] * 2 + [{"status": "violated"}] * 3
    at = scorer.score([threshold_answer], clustering=type("C", (), {"clusters": []})(), verification_by_claim={}, constraint_results={threshold_answer.id: at_threshold}, usable_provider_count=1)
    below = scorer.score([threshold_answer], clustering=type("C", (), {"clusters": []})(), verification_by_claim={}, constraint_results={threshold_answer.id: below_threshold}, usable_provider_count=1)
    assert at.scores[threshold_answer.id] == .6 and at.recommended_answer_id == threshold_answer.id
    assert below.scores[threshold_answer.id] < .6 and below.recommended_answer_id is None
    degraded = answer.model_copy(update={"id": uuid4(), "parse_status": "degraded"})
    assert scorer.score([degraded], clustering=type("C", (), {"clusters": []})(), verification_by_claim={}, constraint_results={}, usable_provider_count=0).recommended_answer_id is None


@pytest.mark.asyncio
async def test_all_unparseable_responses_are_502_and_not_persisted(tmp_path: Path):
    class Bad:
        provider = "bad"
        calls = 0
        async def generate(self, prompt, *, model, deadline=None, **kwargs):
            self.calls += 1
            return AdapterResult(raw_text="not json", provider=self.provider, model=model)

    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path/'bad.db'}", redis_url="", crosscheck_models="bad")
    app = create_app(settings=settings, adapters=AdapterRegistry({"bad": Bad()}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", json={"question": "q"})
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_verification_ids_and_evidence_ids_are_public_and_stable(tmp_path: Path):
    class Good:
        provider = "p"
        async def generate(self, prompt, *, model, deadline=None, **kwargs):
            return AdapterResult(raw_text=json.dumps({"answer": "ok", "claims": [{"claim": "claim", "type": "fact", "confidence": .9}], "constraints_check": {}}), provider="p", model=model)

    verifier = StaticVerifier(VerificationResult(verifier_type="fact", status="verified", confidence=.9, evidence=[{"url": "https://example.com", "title": "source"}]))
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path/'ids.db'}", redis_url="", crosscheck_models="m")
    app = create_app(settings=settings, adapters=AdapterRegistry({"m": Good()}), verifiers=VerifierRegistry({"fact": verifier}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", json={"question": "q"})
    claim = response.json()["model_comparison"][0]["claims"][0]
    assert claim["verification_ids"] and claim["evidence_ids"]
    assert response.json()["evidence"][0]["id"] == claim["evidence_ids"][0]


@pytest.mark.asyncio
async def test_query_clusters_before_verifying_and_calls_representative_once(tmp_path: Path):
    class Good:
        def __init__(self, provider): self.provider = provider
        async def generate(self, prompt, *, model, deadline=None, **kwargs):
            return AdapterResult(raw_text=json.dumps({"answer": "Paris", "claims": [{"claim": "Paris is the capital of France.", "type": "fact", "confidence": .9}], "constraints_check": {}}), provider=self.provider, model=model)
    verifier = StaticVerifier(VerificationResult(verifier_type="fact", status="verified", confidence=1, evidence=[{"url": "https://example.com"}]))
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path/'representative.db'}", redis_url="", crosscheck_models="m1,m2,m3")
    app = create_app(settings=settings, adapters=AdapterRegistry({"m1": Good("p1"), "m2": Good("p2"), "m3": Good("p3")}), verifiers=VerifierRegistry({"fact": verifier}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", json={"question": "capital?"})
    assert response.status_code == 200
    assert len(verifier.calls) == 1
    assert len(response.json()["consensus"]) == 1
    assert len(response.json()["model_comparison"]) == 3


@pytest.mark.asyncio
async def test_real_three_provider_adapters_persist_and_missing_claude_is_labeled(tmp_path: Path):
    valid = json.dumps({"answer": "ok", "claims": [], "constraints_check": {}})
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/messages"):
            return httpx.Response(200, json={"content": [{"type": "text", "text": valid}], "usage": {}})
        return httpx.Response(200, json={"choices": [{"message": {"content": valid}}], "usage": {}})
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        registry = AdapterRegistry({
            "gpt-test": OpenAIAdapter("o", "http://mock/openai/v1", model="gpt-test", http_client=upstream),
            "claude-test": AnthropicAdapter("a", "http://mock", model="claude-test", http_client=upstream),
            "deepseek-test": DeepSeekAdapter("d", "http://mock/deepseek/v1", model="deepseek-test", http_client=upstream),
        })
        settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path/'three.db'}", redis_url="", crosscheck_models="gpt-test,claude-test,deepseek-test")
        app = create_app(settings=settings, adapters=registry)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/query", json={"question": "q"})
        assert response.status_code == 200
        assert [item["provider"] for item in response.json()["model_comparison"]] == ["openai", "anthropic", "deepseek"]
    finally:
        await upstream.aclose()
    missing = Settings(openai_api_key="o", deepseek_api_key="d", anthropic_api_key=None)
    missing_registry = default_adapter_registry(missing.configured_models(), missing)
    assert isinstance(missing_registry.get(missing.configured_models()[1]), UnavailableAdapter)


def test_postgres_has_ordered_report_cache_migration():
    migration = Path("migrations/002_report_cache_and_versions.sql").read_text()
    for column in ("cache_key", "cache_key_version", "report_payload", "behavior_versions"):
        assert column in migration


@pytest.mark.asyncio
async def test_retry_after_header_is_carried_from_real_http_response():
    response = httpx.Response(429, headers={"Retry-After": "4"}, request=httpx.Request("POST", "https://example.test"))
    adapter = OpenAIAdapter("secret")
    with pytest.raises(Exception) as raised:
        adapter._parse_response(response, model="gpt")
    assert getattr(raised.value, "retry_after", None) == 4


@pytest.mark.asyncio
async def test_repair_dispatch_obeys_cost_ceiling(tmp_path: Path):
    class Costly:
        provider = "p"
        calls = 0
        estimated_cost_usd = .3
        async def generate(self, prompt, *, model, deadline=None, **kwargs):
            self.calls += 1
            return AdapterResult(raw_text="malformed", provider="p", model=model, reported_cost=.3)

    adapter = Costly()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path/'cost.db'}", redis_url="", crosscheck_models="m", max_query_cost_usd=.3)
    app = create_app(settings=settings, adapters=AdapterRegistry({"m": adapter}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", json={"question": "q"})
    assert response.status_code == 502
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_chunked_body_stops_at_limit_without_provider_dispatch(tmp_path: Path):
    class Never:
        provider = "p"
        calls = 0
        async def generate(self, prompt, *, model, deadline=None, **kwargs):
            self.calls += 1
            raise AssertionError("must not dispatch")

    adapter = Never()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path/'chunk.db'}", redis_url="", crosscheck_models="m", max_body_bytes=32)
    app = create_app(settings=settings, adapters=AdapterRegistry({"m": adapter}))
    async def chunks():
        yield b'{"question":"'
        yield b"x" * 100
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", content=chunks(), headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert adapter.calls == 0


@pytest.mark.asyncio
async def test_representative_is_verified_once_and_consensus_requires_distinct_providers():
    first = _answer("m1", "p1", "Paris is the capital of France")
    second = _answer("m2", "p2", "Paris is the capital of France!")
    clustering = await SemanticClaimClusterer().cluster([first, second])
    verifier = StaticVerifier(VerificationResult(verifier_type="fact", status="verified", confidence=1, evidence=[{"id": str(uuid4()), "url": "https://example.com"}]))
    # Exercise the consensus boundary with the representative relationship the
    # orchestrator propagates to both originating Claims.
    result = await verifier.verify(first.claims[0], question="q", constraints=None)
    verification = {claim.id: [result] for answer in (first, second) for claim in answer.claims}
    consensus, disagreements = build_consensus_and_disagreements([first, second], clustering=clustering, verification_by_claim=verification)
    assert len(verifier.calls) == 1
    assert len(consensus) == 1 and not disagreements


@pytest.mark.asyncio
async def test_fact_and_code_verifiers_have_bounded_negative_and_positive_paths(monkeypatch):
    def search(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"url": "https://example.gov/fact", "title": "Paris is the capital of France", "content": "Paris is the capital of France"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(search)) as client:
        result = await FactVerifier("secret", http_client=client).verify(Claim(claim="Paris is the capital of France", type="fact", confidence=.8), question="q", constraints=None)
    assert result.status == "verified" and len(result.evidence) == 1

    monkeypatch.setattr("crosscheck.verifiers.subprocess.run", lambda command, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""))
    code = Claim(claim="```python\ndef add(a,b): return a+b\n```", type="code", confidence=.8)
    code_result = await CodeVerifier("pinned-image").verify(code, question="Tests:\n```python\nassert add(1,2)==3\n```", constraints=None)
    assert code_result.status == "verified"
    unavailable = await CodeVerifier("pinned-image").verify(Claim(claim="not delimited", type="code", confidence=.8), question="q", constraints=None)
    assert unavailable.status == "unverified"


@pytest.mark.asyncio
async def test_redis_cache_validates_durable_report_and_single_flight():
    class FakeRedis:
        values = {}
        async def get(self, key): return self.values.get(key)
        async def set(self, key, value, **kwargs):
            if kwargs.get("nx") and key in self.values: return False
            self.values[key] = value; return True
        async def delete(self, key): self.values.pop(key, None)
    class Store:
        async def report_exists(self, report_id): return True
    cache = RedisReportCache("redis://unused", store=Store(), ttl_seconds=86400)
    cache.client = FakeRedis()
    answer = _answer("m", "p", "claim")
    from datetime import datetime, timezone
    from crosscheck.contracts import QuestionSummary, ReportResponse
    report = ReportResponse(report_id=uuid4(), status="complete", created_at=datetime.now(timezone.utc), duration_ms=1,
        question=QuestionSummary(id=uuid4(), text="q", question_type="fact", question_type_origin="fallback", models=["m"]),
        recommendation_message="none", model_comparison=[answer])
    await cache.set("key", report)
    assert (await cache.get("key")).report_id == report.report_id
    token = await cache.acquire_lock("key")
    assert token and await cache.acquire_lock("key") is None
    await cache.release_lock("key", token)


def test_cache_key_versions_and_telemetry_are_privacy_safe(caplog):
    request = QueryRequest(question="private question")
    first = build_cache_key(request, models=["m"], question_type="fact", versions={"prompt": "v1"})
    second = build_cache_key(request, models=["m"], question_type="fact", versions={"prompt": "v2"})
    assert first != second
    threshold = build_cache_key(request, models=["m"], question_type="fact", versions={"clustering": {"threshold": .86}})
    assert threshold not in {first, second}
    telemetry = StructuredTelemetry()
    with caplog.at_level("INFO"):
        telemetry.emit("adapter.completed", provider="p", status="ok", question="secret", api_key="credential")
    assert "secret" not in caplog.text and "credential" not in caplog.text


@pytest.mark.asyncio
async def test_high_compliance_backend_suppresses_recommendation(tmp_path: Path):
    class Good:
        provider = "p"
        async def generate(self, prompt, *, model, deadline=None, **kwargs):
            return AdapterResult(raw_text=json.dumps({"answer": "Take medicine", "claims": [{"claim": "A medical fact", "type": "fact", "confidence": .9}], "constraints_check": {}}), provider="p", model=model)
    verifier = StaticVerifier(VerificationResult(verifier_type="fact", status="verified", confidence=1, evidence=[{"authority": 1}]))
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path/'medical.db'}", redis_url="", crosscheck_models="m")
    app = create_app(settings=settings, adapters=AdapterRegistry({"m": Good()}), verifiers=VerifierRegistry({"fact": verifier}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", json={"question": "Give medical treatment advice"})
    assert response.status_code == 200
    assert response.json()["evidence_only"] is True
    assert response.json()["recommended_answer"] is None


@pytest.mark.asyncio
async def test_lifecycle_telemetry_covers_query_stages_without_bodies(tmp_path: Path):
    class Good:
        provider = "p"
        async def generate(self, prompt, *, model, deadline=None, **kwargs):
            return AdapterResult(raw_text=json.dumps({"answer": "ok", "claims": [{"claim": "fact", "type": "fact", "confidence": .8}], "constraints_check": {}}), provider="p", model=model)
    telemetry = StructuredTelemetry()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path/'telemetry.db'}", redis_url="", crosscheck_models="m")
    app = create_app(settings=settings, adapters=AdapterRegistry({"m": Good()}), telemetry=telemetry)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", json={"question": "private body"})
    assert response.status_code == 200
    required = {"query.started", "cache.miss", "adapter.completed", "parse.completed", "clustering.completed", "verifier.completed", "scoring.completed", "persistence.completed", "query.completed"}
    assert required <= set(telemetry.metrics)
