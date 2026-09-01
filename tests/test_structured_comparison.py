from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from crosscheck.adapters import (
    AdapterRegistry,
    AdapterResult,
    DeepSeekAdapter,
    OpenAIAdapter,
)
from crosscheck.config import Settings
from crosscheck.main import create_app
from crosscheck.parser import parse_structured_answer, parse_with_repair
from crosscheck.persistence import Database
from crosscheck.prompt import build_repair_prompt, build_unified_prompt


VALID = {
    "answer": "Paris",
    "reasoning": "The answer follows from the supplied evidence.",
    "claims": [{"claim": "Paris is the capital of France.", "type": "fact", "confidence": 0.9}],
    "constraints_check": {},
}


@pytest.mark.asyncio
async def test_openai_and_deepseek_use_equivalent_prompt_and_normalized_metadata():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(VALID)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock")
    try:
        prompt = build_unified_prompt(
            "What is the capital of France?",
            {"language": "English"},
            "fact",
            "plain",
        )
        openai = OpenAIAdapter(
            "openai-test-secret",
            "http://mock/openai/v1",
            model="gpt-test",
            http_client=client,
        )
        deepseek = DeepSeekAdapter(
            "deepseek-test-secret",
            "http://mock/deepseek/v1",
            model="deepseek-test",
            http_client=client,
        )
        openai_result = await openai.generate(prompt, model="gpt-test")
        deepseek_result = await deepseek.generate(prompt, model="deepseek-test")
    finally:
        await client.aclose()

    assert len(requests) == 2
    prompts = [json.loads(request.content)["messages"][0]["content"] for request in requests]
    assert prompts[0] == prompts[1] == prompt
    assert "openai-test-secret" not in prompts[0]
    assert "deepseek-test-secret" not in prompts[1]
    assert openai_result.provider == "openai"
    assert deepseek_result.provider == "deepseek"
    assert openai_result.model == "gpt-test"
    assert deepseek_result.model == "deepseek-test"
    assert openai_result.token_usage == {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18}
    assert deepseek_result.token_usage == openai_result.token_usage
    assert openai_result.latency_ms is not None and openai_result.latency_ms >= 0
    assert deepseek_result.latency_ms is not None and deepseek_result.latency_ms >= 0
    assert requests[0].headers["authorization"] == "Bearer openai-test-secret"
    assert requests[1].headers["authorization"] == "Bearer deepseek-test-secret"


def test_parser_accepts_strict_fenced_and_unambiguous_embedded_json_and_ignores_unknown_fields():
    strict = parse_structured_answer(json.dumps({**VALID, "future_field": {"ignored": True}}))
    fenced = parse_structured_answer(f"```json\n{json.dumps(VALID)}\n```")
    embedded = parse_structured_answer(f"Provider note before answer\n{json.dumps(VALID)}\nThanks")

    assert all(parsed.parse_success for parsed in (strict, fenced, embedded))
    assert strict.structured is not None
    assert strict.structured.claims[0].source is None


def test_parser_rejects_invalid_required_shapes_and_ambiguous_objects():
    missing = parse_structured_answer(json.dumps({"answer": "ok", "constraints_check": {}}))
    invalid = parse_structured_answer(
        json.dumps({**VALID, "claims": [{"claim": "x", "type": "fact", "confidence": 2}]})
    )
    ambiguous = parse_structured_answer(f"first {json.dumps(VALID)} second {json.dumps(VALID)}")

    assert missing.parse_status == invalid.parse_status == ambiguous.parse_status == "degraded"
    assert "schema" in invalid.diagnostics[0]
    assert "ambiguous" in ambiguous.diagnostics[0]


@pytest.mark.asyncio
async def test_parse_with_repair_is_bounded_and_runs_once():
    calls: list[str] = []

    async def repair(invalid: str) -> str:
        calls.append(invalid)
        return json.dumps({"answer": "ok", "claims": [], "constraints_check": {}})

    parsed = await parse_with_repair("x" * 500, repair, max_chars=64)
    assert parsed.parse_success
    assert parsed.repair_attempted and parsed.repair_succeeded
    assert calls == ["x" * 64]
    assert parsed.raw_text == "x" * 64


class ScriptedAdapter:
    def __init__(self, provider: str, responses: list[str]) -> None:
        self.provider = provider
        self.responses = responses
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        *,
        model: str,
        deadline: float | None = None,
        **options: Any,
    ) -> AdapterResult:
        del deadline, options
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        return AdapterResult(
            raw_text=response,
            provider=self.provider,
            model=model,
            latency_ms=1,
            token_usage={"total_tokens": 2},
        )


async def _query_client(tmp_path: Path, adapters: AdapterRegistry, *, max_raw_response_chars: int = 120_000):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'comparison.db'}",
        crosscheck_models="openai,deepseek",
        max_raw_response_chars=max_raw_response_chars,
    )
    app = create_app(settings=settings, adapters=adapters)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return app, client


@pytest.mark.asyncio
async def test_http_comparison_repairs_one_provider_and_keeps_answers_side_by_side(tmp_path: Path):
    openai = ScriptedAdapter("openai", ["not-json", json.dumps(VALID)])
    deepseek = ScriptedAdapter("deepseek", [f"note\n{json.dumps(VALID)}"])
    _, client = await _query_client(tmp_path, AdapterRegistry({"openai": openai, "deepseek": deepseek}))
    async with client:
        response = await client.post(
            "/api/query",
            json={
                "question": "What is the capital of France?",
                "constraints": {"language": "English"},
                "expected_output_format": "plain",
                "models": ["openai", "deepseek"],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert [answer["provider"] for answer in body["model_comparison"]] == ["openai", "deepseek"]
    assert all(answer["parse_status"] == "parsed" for answer in body["model_comparison"])
    assert body["model_comparison"][0]["parse_diagnostics"] == ["structured response repaired"]
    assert len(openai.prompts) == 2
    assert "Previous response" in openai.prompts[1]
    assert "English" in openai.prompts[0]


@pytest.mark.asyncio
async def test_repair_failure_is_bounded_persisted_degraded_and_not_recommended(tmp_path: Path):
    original = "provider plain text " + ("x" * 200)
    openai = ScriptedAdapter("openai", [original, "still malformed"])
    deepseek = ScriptedAdapter("deepseek", [json.dumps(VALID)])
    _, client = await _query_client(
        tmp_path,
        AdapterRegistry({"openai": openai, "deepseek": deepseek}),
        max_raw_response_chars=80,
    )
    async with client:
        response = await client.post(
            "/api/query",
            json={"question": "What is the capital of France?", "models": ["openai", "deepseek"]},
        )
    assert response.status_code == 200
    body = response.json()
    degraded = body["model_comparison"][0]
    assert body["status"] == "partial"
    assert degraded["parse_status"] == "degraded"
    assert len(degraded["answer"]) == 80
    assert degraded["claims"] == []
    assert degraded["constraints_check"] == {}
    assert degraded["score"] == 0
    assert body["recommended_answer"] is None
    assert any("unparseable" in warning for warning in body["warnings"])

    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'comparison.db'}")
    await database.initialize()
    async with database.engine.connect() as connection:
        row = (
            await connection.execute(text("SELECT raw_response, parse_status, score FROM answers WHERE model_name='openai'"))
        ).one()
    await database.dispose()
    assert row.parse_status == "degraded"
    assert row.score == 0
    assert len(row.raw_response) == 80


def test_repair_prompt_has_schema_and_no_transport_secret():
    prompt = build_repair_prompt("bad", original_prompt=build_unified_prompt("Question", None, "fact", None))
    assert "structured response repair" in prompt
    assert "previous-response" in prompt
    assert "constraints_check" in prompt
    assert "Authorization" not in prompt
