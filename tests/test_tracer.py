from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from crosscheck.adapters import AdapterRegistry, DeterministicAdapter
from crosscheck.config import Settings
from crosscheck.contracts import VerificationResult
from crosscheck.main import create_app
from crosscheck.persistence import Database, ReportStore
from crosscheck.verifiers import StaticVerifier, VerifierRegistry


async def make_client(tmp_path: Path, *, store: ReportStore | None = None, verifiers=None):
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'crosscheck.db'}"
    settings = Settings(database_url=db_url, crosscheck_models="deterministic")
    app = create_app(
        settings=settings,
        store=store,
        adapters=AdapterRegistry({"deterministic": DeterministicAdapter()}),
        verifiers=verifiers,
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return app, client


@pytest.mark.asyncio
async def test_health_is_exact_and_query_persists_graph(tmp_path: Path):
    _, client = await make_client(tmp_path)
    async with client:
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        response = await client.post("/api/query", json={"question": "Who wrote this?"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        assert "one or more verifier checks were unavailable" in body["warnings"]
        assert body["question"]["question_type"] == "fact"
        assert body["question"]["question_type_origin"] == "classifier"
        answer = body["model_comparison"][0]
        assert answer["id"]
        assert answer["claims"][0]["id"]
        assert body["report_id"]

    # The same SQLite file is the durable source and contains the complete graph.
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'crosscheck.db'}")
    await db.initialize()
    async with db.engine.connect() as connection:
        counts = {}
        for table in ("questions", "answers", "claims", "reports"):
            counts[table] = (await connection.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
    await db.dispose()
    assert counts == {"questions": 1, "answers": 1, "claims": 1, "reports": 1}


@pytest.mark.asyncio
async def test_validation_and_classification_precedence(tmp_path: Path):
    _, client = await make_client(tmp_path)
    async with client:
        for payload in (
            {"question": "  "},
            {"question": "hello", "unexpected": True},
            {"question": "hello", "question_type": "unsupported"},
            {"question": "hello", "expected_output_format": "cards"},
            {"question": "hello", "models": []},
        ):
            response = await client.post("/api/query", json=payload)
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "VALIDATION_ERROR"

        response = await client.post(
            "/api/query",
            json={
                "question": "Implement a Python sorting function",
                "constraints": {"budget": 100},
                "question_type": "auto",
            },
        )
        assert response.status_code == 200
        assert response.json()["question"]["question_type_origin"] == "deterministic_code"

        response = await client.post(
            "/api/query",
            json={
                "question": "Recommend a laptop",
                "constraints": {"budget": 5000},
            },
        )
        assert response.status_code == 200
        assert response.json()["question"]["question_type_origin"] == "deterministic_constraints"

        response = await client.post(
            "/api/query",
            json={"question": "Implement a Python function", "question_type": "fact"},
        )
        assert response.status_code == 200
        assert response.json()["question"]["question_type"] == "fact"
        assert response.json()["question"]["question_type_origin"] == "explicit"


@pytest.mark.asyncio
async def test_atomic_report_write_rolls_back(tmp_path: Path):
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'atomic.db'}"
    database = Database(db_url)

    def inject(point: str):
        if point == "claim":
            raise RuntimeError("injected failure")

    store = ReportStore(database, failure_hook=inject)
    _, client = await make_client(tmp_path, store=store)
    async with client:
        response = await client.post("/api/query", json={"question": "Atomic write?"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "REPORT_PERSISTENCE_UNAVAILABLE"

    await database.initialize()
    async with database.engine.connect() as connection:
        for table in ("questions", "answers", "claims", "reports"):
            count = (await connection.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
            assert count == 0
    await database.dispose()


@pytest.mark.asyncio
async def test_injected_verifier_is_provider_neutral(tmp_path: Path):
    verifier = StaticVerifier(VerificationResult(status="verified", confidence=0.9))
    _, client = await make_client(tmp_path, verifiers=VerifierRegistry({"*": verifier}))
    async with client:
        response = await client.post("/api/query", json={"question": "What is durable?"})
        assert response.status_code == 200
        claim = response.json()["model_comparison"][0]["claims"][0]
        assert claim["verification_status"] == "verified"
        assert verifier.calls == [claim["claim"]]


@pytest.mark.asyncio
async def test_classifier_uncertainty_uses_conservative_fact_fallback(tmp_path: Path):
    def unavailable_classifier(question, constraints):
        del question, constraints
        raise RuntimeError("classifier unavailable")

    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'fallback.db'}", crosscheck_models="deterministic")
    app = create_app(
        settings=settings,
        adapters=AdapterRegistry({"deterministic": DeterministicAdapter()}),
        classifier=unavailable_classifier,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", json={"question": "An ambiguous prompt"})
    assert response.status_code == 200
    assert response.json()["question"]["question_type"] == "fact"
    assert response.json()["question"]["question_type_origin"] == "fallback"
