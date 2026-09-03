from __future__ import annotations

import sys
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from crosscheck.constraints import IndependentConstraintService
from crosscheck.clustering import ClaimCluster, ClusteringOutcome
from crosscheck.contracts import Claim, ModelAnswer, QueryRequest, VerificationResult
from crosscheck.scoring import EvidenceScorer
from crosscheck.verifiers import CodeVerifier, FactVerifier


def _answer(text: str) -> ModelAnswer:
    return ModelAnswer(id=uuid4(), model="m", provider="p", answer=text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "expected_authority"),
    [
        ("https://en.wikipedia.org/wiki/Paris", 0.55),
        ("https://reuters.com.deceptive.example/story", 0.55),
    ],
)
async def test_fact_verifier_does_not_verify_from_weak_or_deceptive_single_source(
    url: str,
    expected_authority: float,
) -> None:
    def search(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": url,
                        "title": "Paris is the capital of France",
                        "content": "Paris is the capital of France",
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

    assert result.status == "unverified"
    assert result.evidence[0]["authority"] == expected_authority


@pytest.mark.asyncio
async def test_fact_verifier_accepts_one_actual_high_authority_host() -> None:
    def search(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://data.example.gov/facts/paris",
                        "title": "Paris is the capital of France",
                        "content": "Paris is the capital of France",
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

    assert result.status == "verified"
    assert result.evidence[0]["domain"] == "data.example.gov"


@pytest.mark.asyncio
async def test_constraint_verifier_refuses_currency_mismatch() -> None:
    service = IndependentConstraintService()
    request = QueryRequest(
        question="pick one",
        constraints={"budget": {"value": 5000, "currency": "USD"}},
    )

    mismatch = await service.check(request, [_answer("Price: ¥4500")])
    mismatch_check = next(iter(mismatch.per_answer.values()))[0]
    assert mismatch_check["status"] == "indeterminate"
    assert mismatch_check["expected"] == {"value": 5000.0, "currency": "USD"}
    assert mismatch_check["observed"] == {"value": 4500.0, "currency": "CNY"}
    assert "currency" in mismatch_check["reason"]

    comparable = await service.check(request, [_answer("Price: $4500 USD")])
    assert next(iter(comparable.per_answer.values()))[0]["status"] == "satisfied"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("constraint", "answer", "expected_status"),
    [
        ({"duration": "2 hours"}, "Duration: 90 minutes", "satisfied"),
        ({"weight": {"value": 2, "unit": "kg"}}, "Weight: 2,100 g", "violated"),
        ({"dimensions": "30 x 20 x 10 cm"}, "Dimensions: 29 x 19 x 9 cm", "satisfied"),
        (
            {"dimensions": {"value": [30, 20, 10], "unit": "cm", "dimension": "length"}},
            "Dimensions: 31 x 19 x 9 cm",
            "violated",
        ),
        ({"max_percentage": "20%"}, "Percentage: 21 percent", "violated"),
        ({"duration": "2 hours"}, "Weight: 90 kg", "indeterminate"),
    ],
)
async def test_constraint_verifier_normalizes_numeric_units_and_dimensions(
    constraint: dict[str, object],
    answer: str,
    expected_status: str,
) -> None:
    outcome = await IndependentConstraintService().check(
        QueryRequest(question="pick one", constraints=constraint),
        [_answer(answer)],
    )

    check = next(iter(outcome.per_answer.values()))[0]
    assert check["status"] == expected_status
    assert check["comparator"] == "lte"
    if expected_status != "indeterminate":
        assert check["expected"]["dimension"] in {"duration", "weight", "length", "percentage"}
        assert check["observed"]["dimension"] == check["expected"]["dimension"]


def test_scorer_enforces_provider_and_independent_verification_caps() -> None:
    scorer = EvidenceScorer()
    answer = ModelAnswer(
        id=uuid4(),
        model="m1",
        provider="p1",
        answer="answer",
        claims=[Claim(id=uuid4(), claim="fact", type="fact", confidence=0.9)],
    )
    claim_id = answer.claims[0].id
    assert claim_id
    verified = VerificationResult(status="verified", confidence=1.0, evidence=[{"authority": 1.0, "relation": "supporting"}])

    one_provider = scorer.score(
        [answer],
        clustering=ClusteringOutcome(),
        verification_by_claim={claim_id: [verified]},
        constraint_results={},
        usable_provider_count=1,
    )
    assert one_provider.scores[answer.id] == 0.59
    assert one_provider.recommended_answer_id is None
    assert one_provider.components[answer.id]["assurance_cap"]["reason"] == "only one usable provider"

    second = answer.model_copy(update={"id": uuid4(), "model": "m2", "provider": "p2", "claims": []})
    no_verification = scorer.score(
        [answer.model_copy(update={"claims": []}), second],
        clustering=ClusteringOutcome(),
        verification_by_claim={},
        constraint_results={answer.id: [{"status": "satisfied"}], second.id: [{"status": "satisfied"}]},
        usable_provider_count=2,
    )
    assert no_verification.scores[answer.id] == 0.59
    assert no_verification.recommended_answer_id is None
    assert no_verification.components[answer.id]["assurance_cap"]["reason"] == "no successful independent verification"


def test_consensus_component_counts_unique_cluster_memberships() -> None:
    first = Claim(id=uuid4(), claim="same fact", type="fact", confidence=0.9)
    duplicate = Claim(id=uuid4(), claim="same fact!", type="fact", confidence=0.8)
    singleton = Claim(id=uuid4(), claim="other fact", type="fact", confidence=0.7)
    peer = Claim(id=uuid4(), claim="same fact.", type="fact", confidence=0.9)
    answer = ModelAnswer(id=uuid4(), model="m1", provider="p1", answer="a", claims=[first, duplicate, singleton])
    other = ModelAnswer(id=uuid4(), model="m2", provider="p2", answer="b", claims=[peer])
    consensus_cluster = ClaimCluster(
        id=uuid4(),
        representative_text=first.claim,
        representative_claim_id=first.id,
        claim_ids=[first.id, duplicate.id, peer.id],
        supporting_models=["m1", "m2"],
    )
    singleton_cluster = ClaimCluster(
        id=uuid4(),
        representative_text=singleton.claim,
        representative_claim_id=singleton.id,
        claim_ids=[singleton.id],
        supporting_models=["m1"],
    )
    verified = VerificationResult(status="verified", confidence=1.0, evidence=[{"authority": 1.0, "relation": "supporting"}])
    outcome = EvidenceScorer().score(
        [answer, other],
        clustering=ClusteringOutcome(clusters=[consensus_cluster, singleton_cluster]),
        verification_by_claim={first.id: [verified], duplicate.id: [verified], peer.id: [verified]},
        constraint_results={},
        usable_provider_count=2,
    )

    component = outcome.components[answer.id]["consensus"]
    assert component["numerator"] == 1
    assert component["denominator"] == 2
    assert component["score"] == 0.5


def test_sandbox_process_is_terminated_at_combined_output_limit() -> None:
    result = CodeVerifier._run_bounded(
        [sys.executable, "-c", "import sys; print('o' * 10000); print('e' * 10000, file=sys.stderr)"],
        "",
        timeout_seconds=2.0,
        max_output_bytes=256,
    )

    assert result.output_truncated is True
    assert len(result.stdout.encode()) + len(result.stderr.encode()) <= 256


@pytest.mark.asyncio
async def test_code_verifier_applies_complete_docker_resource_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def bounded(command: list[str], script: str, *, timeout_seconds: float, max_output_bytes: int):
        captured.update(command=command, script=script, timeout=timeout_seconds, output_limit=max_output_bytes)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="", output_truncated=False, timed_out=False)

    monkeypatch.setattr(CodeVerifier, "_run_bounded", staticmethod(bounded))
    verifier = CodeVerifier("crosscheck-python-sandbox:3.11.9")
    result = await verifier.verify(
        Claim(claim="```python\ndef add(a, b): return a + b\n```", type="code", confidence=0.9),
        question="```python\nassert add(1, 2) == 3\n```",
        constraints=None,
    )

    command = captured["command"]
    assert isinstance(command, list)
    for required in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=128m",
        "--memory-swap=128m",
        "--cpus=.5",
        "--pids-limit=64",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
        "--ulimit=nofile=64:64",
        "--pull=never",
    ):
        assert required in command
    assert result.status == "verified"
    assert result.details["stdout"] == "ok"
    assert result.details["stderr"] == ""
    assert result.details["output_truncated"] is False


@pytest.mark.asyncio
async def test_code_verifier_counts_each_assertion_in_explicit_test_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def bounded(command: list[str], script: str, **kwargs: object):
        captured["script"] = script
        return SimpleNamespace(returncode=0, stdout="", stderr="", output_truncated=False, timed_out=False)

    monkeypatch.setattr(CodeVerifier, "_run_bounded", staticmethod(bounded))
    result = await CodeVerifier("pinned-image").verify(
        Claim(claim="```python\ndef add(a, b): return a + b\n```", type="code", confidence=0.9),
        question=(
            "Example only:\n```python\nprint(add(20, 22))\n```\n"
            "Tests:\n```python\nimport pytest\nassert add(1, 2) == 3\n"
            "with pytest.raises(TypeError):\n    add('one', 2)\n```\n"
            "More tests:\n```python\nclass TestAdd:\n"
            "    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n```"
        ),
        constraints=None,
    )

    assert result.status == "verified"
    assert result.details["passed_tests"] == 3
    assert result.details["total_tests"] == 3
    assert "print(add(20, 22))" not in captured["script"]


@pytest.mark.asyncio
async def test_code_verifier_does_not_execute_non_test_fences(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        CodeVerifier,
        "_run_bounded",
        staticmethod(lambda *args, **kwargs: pytest.fail("non-test snippets must not execute")),
    )

    result = await CodeVerifier("pinned-image").verify(
        Claim(claim="```python\ndef add(a, b): return a + b\n```", type="code", confidence=0.9),
        question="Example:\n```python\nprint(add(1, 2))\n```",
        constraints=None,
    )

    assert result.status == "unverified"
    assert result.details["reason"] == "clearly delimited Python code and explicit tests are required"
