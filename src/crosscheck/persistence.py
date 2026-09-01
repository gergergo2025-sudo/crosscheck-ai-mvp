"""PostgreSQL-backed durable Report graph and explicit migrations.

The repository intentionally uses a small SQL boundary instead of leaking an ORM
model into the domain contracts.  PostgreSQL is the production dialect; SQLite is
supported only as a lightweight deterministic test/development backend.
"""

from __future__ import annotations

import inspect
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping
from uuid import UUID, uuid4

from sqlalchemy import JSON, bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from .contracts import (
    FeedbackRequest,
    FeedbackResponse,
    ModelAnswer,
    QueryRequest,
    ReportResponse,
    VerificationResult,
)


class PersistenceError(RuntimeError):
    """Safe wrapper for database and migration failures."""


class AtomicWriteError(PersistenceError):
    """Raised by a test failure injector to prove transaction rollback."""


FailureHook = Callable[[str], None | Awaitable[None]]


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _async_url(url: str) -> str:
    """Accept familiar sync-style URLs while selecting the async drivers."""

    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("sqlite://"):
        return "sqlite+aiosqlite://" + url.removeprefix("sqlite://")
    return url


def _json_bind(statement: str, fields: Iterable[str]):
    params = [bindparam(field, type_=JSON) for field in fields]
    return text(statement).bindparams(*params)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _iso(value: datetime | None = None) -> datetime:
    return value or datetime.now(timezone.utc)


class Database:
    """Lazy async database engine with explicit, idempotent migrations."""

    def __init__(self, url: str) -> None:
        self.url = _async_url(url)
        self.engine: AsyncEngine | None = None
        self.migrated = False

    async def initialize(self) -> None:
        if self.engine is None:
            kwargs: dict[str, Any] = {"pool_pre_ping": True}
            if _is_sqlite(self.url):
                kwargs["connect_args"] = {"check_same_thread": False}
                if ":memory:" in self.url:
                    # A single connection keeps the migration-created schema
                    # visible to subsequent transactions in test fixtures.
                    kwargs["poolclass"] = StaticPool
            self.engine = create_async_engine(self.url, **kwargs)
        if not self.migrated:
            await self.migrate()

    async def migrate(self) -> None:
        if self.engine is None:
            raise PersistenceError("database engine is not initialized")
        migration_name = "001_initial_sqlite.sql" if _is_sqlite(self.url) else "001_initial.sql"
        migration_path = Path(__file__).resolve().parents[2] / "migrations" / migration_name
        if not migration_path.exists():
            raise PersistenceError(f"migration file is missing: {migration_name}")
        script = migration_path.read_text(encoding="utf-8")
        statements = [part.strip() for part in re.split(r";\s*(?:\n|$)", script) if part.strip()]
        async with self.engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
        self.migrated = True

    @asynccontextmanager
    async def transaction(self):
        await self.initialize()
        assert self.engine is not None
        async with self.engine.begin() as connection:
            yield connection

    async def dispose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None
            self.migrated = False


class ReportStore:
    """Atomic graph writer and minimal lookup boundary used by the tracer."""

    def __init__(self, database: Database, *, failure_hook: FailureHook | None = None) -> None:
        self.database = database
        self.failure_hook = failure_hook

    async def _hook(self, point: str) -> None:
        if self.failure_hook is None:
            return
        result = self.failure_hook(point)
        if inspect.isawaitable(result):
            await result

    async def persist_report(
        self,
        report: ReportResponse,
        request: QueryRequest,
        *,
        request_id: UUID,
        raw_by_answer: dict[UUID, str] | None = None,
        verification_by_claim: dict[UUID, list[VerificationResult]] | None = None,
        cache_key: str | None = None,
        cache_key_version: str | None = None,
    ) -> ReportResponse:
        """Insert Question → Answer → Claim → Verification → Report atomically."""

        raw_by_answer = raw_by_answer or {}
        verification_by_claim = verification_by_claim or {}
        created_at = _iso(report.created_at)
        try:
            async with self.database.transaction() as connection:
                await connection.execute(
                    text(
                        """INSERT INTO questions
                        (id, text, constraints, question_type, question_type_origin,
                         expected_output_format, selected_models, request_id, created_at)
                        VALUES (:id, :text, :constraints, :question_type,
                         :question_type_origin, :expected_output_format,
                         :selected_models, :request_id, :created_at)"""
                    ).bindparams(
                        bindparam("constraints", type_=JSON),
                        bindparam("selected_models", type_=JSON),
                    ),
                    {
                        "id": str(report.question.id),
                        "text": request.question,
                        "constraints": request.constraints,
                        "question_type": report.question.question_type,
                        "question_type_origin": report.question.question_type_origin,
                        "expected_output_format": report.question.expected_output_format,
                        "selected_models": report.question.models,
                        "request_id": str(request_id),
                        "created_at": created_at,
                    },
                )
                await self._hook("question")

                for answer in report.model_comparison:
                    await connection.execute(
                        _json_bind(
                            """INSERT INTO answers
                            (id, question_id, provider, model_name, raw_response,
                             structured_answer, parse_status, parse_diagnostics,
                             score, score_components, latency_ms, token_usage,
                             reported_cost, retry_count, provider_status,
                             failure_class, created_at)
                            VALUES (:id, :question_id, :provider, :model_name,
                             :raw_response, :structured_answer, :parse_status,
                             :parse_diagnostics, :score, :score_components,
                             :latency_ms, :token_usage, :reported_cost,
                             :retry_count, :provider_status, :failure_class,
                             :created_at)""",
                            {"structured_answer", "parse_diagnostics", "score_components", "token_usage"},
                        ),
                        {
                            "id": str(answer.id),
                            "question_id": str(report.question.id),
                            "provider": answer.provider,
                            "model_name": answer.model,
                            "raw_response": raw_by_answer.get(answer.id, answer.answer),
                            "structured_answer": {
                                "answer": answer.answer,
                                "reasoning": answer.reasoning,
                                "claims": [claim.model_dump(mode="json") for claim in answer.claims],
                                "constraints_check": answer.constraints_check,
                            },
                            "parse_status": answer.parse_status,
                            "parse_diagnostics": answer.parse_diagnostics,
                            "score": answer.score,
                            "score_components": answer.score_components,
                            "latency_ms": answer.latency_ms,
                            "token_usage": answer.token_usage,
                            "reported_cost": answer.reported_cost,
                            "retry_count": answer.retry_count,
                            "provider_status": answer.provider_status,
                            "failure_class": answer.failure_class,
                            "created_at": created_at,
                        },
                    )
                    await self._hook("answer")

                    for claim in answer.claims:
                        if claim.id is None:
                            raise PersistenceError("claim IDs must be assigned before persistence")
                        await connection.execute(
                            _json_bind(
                                """INSERT INTO claims
                                (id, answer_id, claim_text, normalized_text, claim_type,
                                 source, self_confidence, assumptions, cluster_id,
                                 verification_status, verification_confidence,
                                 evidence_ids, created_at)
                                VALUES (:id, :answer_id, :claim_text, :normalized_text,
                                 :claim_type, :source, :self_confidence, :assumptions,
                                 :cluster_id, :verification_status,
                                 :verification_confidence, :evidence_ids, :created_at)""",
                                {"evidence_ids"},
                            ),
                            {
                                "id": str(claim.id),
                                "answer_id": str(answer.id),
                                "claim_text": claim.claim,
                                "normalized_text": " ".join(claim.claim.casefold().split()),
                                "claim_type": claim.type,
                                "source": claim.source,
                                "self_confidence": claim.confidence,
                                "assumptions": claim.assumptions,
                                "cluster_id": str(claim.cluster_id) if claim.cluster_id else None,
                                "verification_status": claim.verification_status,
                                "verification_confidence": claim.verification_confidence,
                                "evidence_ids": [str(item) for item in claim.evidence_ids],
                                "created_at": created_at,
                            },
                        )
                        await self._hook("claim")
                        for verification in verification_by_claim.get(claim.id, []):
                            verification_id = verification.id or uuid4()
                            await connection.execute(
                                _json_bind(
                                    """INSERT INTO verification_results
                                    (id, claim_id, verifier_type, verifier_version,
                                     status, verified, confidence, evidence, details,
                                     duration_ms, failure_class, created_at)
                                    VALUES (:id, :claim_id, :verifier_type,
                                     :verifier_version, :status, :verified,
                                     :confidence, :evidence, :details, :duration_ms,
                                     :failure_class, :created_at)""",
                                    {"evidence", "details"},
                                ),
                                {
                                    "id": str(verification_id),
                                    "claim_id": str(claim.id),
                                    "verifier_type": verification.verifier_type,
                                    "verifier_version": verification.verifier_version,
                                    "status": verification.status,
                                    "verified": verification.status == "verified",
                                    "confidence": verification.confidence,
                                    "evidence": verification.evidence,
                                    "details": verification.details,
                                    "duration_ms": verification.duration_ms,
                                    "failure_class": verification.failure_class,
                                    "created_at": created_at,
                                },
                            )

                await connection.execute(
                    _json_bind(
                        """INSERT INTO reports
                        (id, question_id, recommended_answer_id, status,
                         recommendation_message, consensus, disagreements,
                         model_scores, constraints_check, evidence, warnings,
                         prompt_version, cache_key, cache_key_version,
                         report_payload, total_duration_ms, created_at)
                        VALUES (:id, :question_id, :recommended_answer_id, :status,
                         :recommendation_message, :consensus, :disagreements,
                         :model_scores, :constraints_check, :evidence, :warnings,
                         :prompt_version, :cache_key, :cache_key_version,
                         :report_payload, :total_duration_ms, :created_at)""",
                        {
                            "consensus",
                            "disagreements",
                            "model_scores",
                            "constraints_check",
                            "evidence",
                            "warnings",
                            "report_payload",
                        },
                    ),
                    {
                        "id": str(report.report_id),
                        "question_id": str(report.question.id),
                        "recommended_answer_id": (
                            str(report.recommended_answer.id) if report.recommended_answer else None
                        ),
                        "status": report.status,
                        "recommendation_message": report.recommendation_message,
                        "consensus": report.consensus,
                        "disagreements": report.disagreements,
                        "model_scores": {
                            str(answer.id): {"model": answer.model, "score": answer.score}
                            for answer in report.model_comparison
                        },
                        "constraints_check": report.constraints_check,
                        "evidence": report.evidence,
                        "warnings": report.warnings,
                        "prompt_version": "unified-v1",
                        "cache_key": cache_key,
                        "cache_key_version": cache_key_version,
                        # Keep a validated, immutable response snapshot so a
                        # cache hit can rehydrate the exact public Report while
                        # PostgreSQL remains authoritative for existence and
                        # ownership checks.
                        "report_payload": {
                            "report": report.model_dump(mode="json"),
                            "cache_key": cache_key,
                            "cache_key_version": cache_key_version,
                        },
                        "total_duration_ms": report.duration_ms,
                        "created_at": created_at,
                    },
                )
                await self._hook("report")
        except AtomicWriteError:
            raise
        except PersistenceError:
            raise
        except Exception as exc:
            raise PersistenceError("report persistence failed") from exc
        return report

    async def report_exists(self, report_id: UUID) -> bool:
        await self.database.initialize()
        assert self.database.engine is not None
        async with self.database.engine.connect() as connection:
            result = await connection.execute(text("SELECT 1 FROM reports WHERE id = :id"), {"id": str(report_id)})
            return result.first() is not None

    async def claim_belongs_to_report(self, report_id: UUID, claim_id: UUID) -> bool:
        await self.database.initialize()
        assert self.database.engine is not None
        query = text(
            """SELECT 1 FROM claims c
            JOIN answers a ON a.id = c.answer_id
            JOIN reports r ON r.question_id = a.question_id
            WHERE r.id = :report_id AND c.id = :claim_id"""
        )
        async with self.database.engine.connect() as connection:
            result = await connection.execute(query, {"report_id": str(report_id), "claim_id": str(claim_id)})
            return result.first() is not None

    async def create_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        if not await self.report_exists(request.report_id):
            raise PersistenceError("report not found")
        if request.claim_id and not await self.claim_belongs_to_report(request.report_id, request.claim_id):
            raise PersistenceError("claim does not belong to report")
        feedback_id = uuid4()
        created_at = _iso()
        try:
            async with self.database.transaction() as connection:
                await connection.execute(
                    text(
                        """INSERT INTO feedback
                        (id, report_id, helpful, claim_id, comment,
                         suggested_answer, created_at)
                        VALUES (:id, :report_id, :helpful, :claim_id, :comment,
                         :suggested_answer, :created_at)"""
                    ),
                    {
                        "id": str(feedback_id),
                        "report_id": str(request.report_id),
                        "helpful": request.helpful,
                        "claim_id": str(request.claim_id) if request.claim_id else None,
                        "comment": request.comment,
                        "suggested_answer": request.suggested_answer,
                        "created_at": created_at,
                    },
                )
        except Exception as exc:
            raise PersistenceError("feedback persistence failed") from exc
        return FeedbackResponse(feedback_id=feedback_id, report_id=request.report_id, created_at=created_at)
