"""Single-turn Question-to-Report orchestration for the durable tracer."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Awaitable
from uuid import UUID, uuid4

from .adapters import AdapterError, AdapterRegistry
from .classification import Classifier, resolve_classification
from .config import Settings
from .contracts import (
    AdapterResult,
    Claim,
    ModelAnswer,
    QueryRequest,
    QuestionSummary,
    ReportResponse,
    VerificationResult,
)
from .errors import (
    ModelConfigurationUnavailable,
    NoUsableModelAnswer,
    ReportPersistenceUnavailable,
    RequestValidationError,
)
from .parser import parse_structured_answer
from .persistence import PersistenceError, ReportStore
from .prompt import build_unified_prompt
from .verifiers import VerifierRegistry


def _bounded_text(value: str, limit: int) -> str:
    return (value or "")[:limit]


def _adapter_result(value: AdapterResult | Mapping[str, Any] | str, *, model: str) -> AdapterResult:
    if isinstance(value, AdapterResult):
        return value
    if isinstance(value, str):
        return AdapterResult(raw_text=value, provider="unknown", model=model)
    return AdapterResult.model_validate({"model": model, **dict(value)})


def _safe_failure_class(exc: BaseException) -> str:
    if isinstance(exc, AdapterError):
        return getattr(exc, "failure_class", "adapter_error")
    return "adapter_error"


class QueryService:
    """Coordinates ports and persists one immutable Report graph per request."""

    def __init__(
        self,
        *,
        settings: Settings,
        store: ReportStore,
        adapters: AdapterRegistry,
        verifiers: VerifierRegistry | None = None,
        classifier: Classifier | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.adapters = adapters
        self.verifiers = verifiers or VerifierRegistry()
        self.classifier = classifier

    def _selected_models(self, request: QueryRequest) -> list[str]:
        selected = request.models or self.settings.configured_models()
        if not selected:
            raise ModelConfigurationUnavailable()
        known = self.adapters.known_models()
        unknown = [model for model in selected if model not in known]
        if unknown:
            raise RequestValidationError(
                "one or more requested models are not allow-listed",
                details={"models": unknown},
            )
        if not self.adapters.usable_models().intersection(selected):
            raise ModelConfigurationUnavailable()
        return selected

    async def _call_adapter(
        self,
        model: str,
        prompt: str,
        *,
        deadline: float,
    ) -> tuple[str, AdapterResult | None, BaseException | None]:
        adapter = self.adapters.get(model)
        try:
            remaining = max(0.001, deadline - time.monotonic())
            result = await asyncio.wait_for(
                adapter.generate(prompt, model=model, deadline=deadline),
                timeout=remaining,
            )
            return model, _adapter_result(result, model=model), None
        except asyncio.TimeoutError as exc:
            return model, None, exc
        except BaseException as exc:  # provider isolation: siblings keep running
            return model, None, exc

    async def _verify_claim(
        self,
        claim: Claim,
        *,
        question: str,
        constraints: dict[str, Any] | str | None,
        deadline: float,
    ) -> tuple[Claim, VerificationResult]:
        verifier = self.verifiers.get(claim.type)
        try:
            remaining = max(0.001, deadline - time.monotonic())
            result = await asyncio.wait_for(
                verifier.verify(
                    claim,
                    question=question,
                    constraints=constraints,
                    deadline=deadline,
                ),
                timeout=remaining,
            )
            if not isinstance(result, VerificationResult):
                result = VerificationResult.model_validate(result)
        except asyncio.TimeoutError:
            result = VerificationResult(status="unavailable", failure_class="timeout", details={"reason": "deadline"})
        except BaseException:
            result = VerificationResult(status="unavailable", failure_class="verifier_error", details={"reason": "verifier failed"})
        updated = claim.model_copy(
            update={
                "verification_status": result.status,
                "verification_confidence": result.confidence,
            }
        )
        return updated, result

    async def execute(self, request: QueryRequest, *, request_id: UUID | None = None) -> ReportResponse:
        started = time.perf_counter()
        request_id = request_id or uuid4()
        if len(request.question) > self.settings.max_question_length:
            raise RequestValidationError(
                "question is too long",
                details={"question": ["maximum length exceeded"]},
            )
        selected_models = self._selected_models(request)
        deadline = time.monotonic() + self.settings.query_deadline_seconds
        classification = await resolve_classification(
            request.question,
            request.constraints,
            request.question_type,
            self.classifier,
        )
        prompt = build_unified_prompt(
            request.question,
            request.constraints,
            classification.question_type,
            request.expected_output_format,
            version=self.settings.prompt_version,
        )

        results = await asyncio.gather(
            *(self._call_adapter(model, prompt, deadline=deadline) for model in selected_models)
        )
        model_answers: list[ModelAnswer] = []
        raw_by_answer: dict[UUID, str] = {}
        failures: list[tuple[str, BaseException]] = []
        verification_by_claim: dict[UUID, list[VerificationResult]] = {}

        for model, adapter_result, failure in results:
            if failure is not None or adapter_result is None:
                assert failure is not None
                failures.append((model, failure))
                model_answers.append(
                    ModelAnswer(
                        id=uuid4(),
                        model=model,
                        provider="unknown",
                        answer="Provider did not return an answer.",
                        reasoning="",
                        parse_status="degraded",
                        parse_diagnostics=["provider call failed"],
                        score=0.0,
                        provider_status="unavailable",
                        failure_class=_safe_failure_class(failure),
                    )
                )
                continue

            answer_id = uuid4()
            raw_text = _bounded_text(adapter_result.raw_text, self.settings.max_raw_response_chars)
            parsed = parse_structured_answer(raw_text, max_chars=self.settings.max_raw_response_chars)
            if parsed.structured is None:
                model_answer = ModelAnswer(
                    id=answer_id,
                    model=model,
                    provider=adapter_result.provider,
                    answer=_bounded_text(raw_text or "No answer text was returned.", 100_000),
                    reasoning="",
                    claims=[],
                    constraints_check={},
                    parse_status="degraded",
                    parse_diagnostics=parsed.diagnostics,
                    score=0.0,
                    latency_ms=adapter_result.latency_ms,
                    token_usage=adapter_result.token_usage,
                    reported_cost=adapter_result.reported_cost,
                    retry_count=adapter_result.retry_count,
                    provider_status=adapter_result.status,
                    failure_class=adapter_result.failure_class,
                )
                model_answers.append(model_answer)
                raw_by_answer[answer_id] = raw_text
                continue

            claims: list[Claim] = []
            for claim in parsed.structured.claims:
                claims.append(claim.model_copy(update={"id": uuid4()}))
            model_answer = ModelAnswer(
                id=answer_id,
                model=model,
                provider=adapter_result.provider,
                answer=parsed.structured.answer,
                reasoning=parsed.structured.reasoning,
                claims=claims,
                constraints_check=parsed.structured.constraints_check,
                parse_status="parsed",
                parse_diagnostics=[],
                score=0.0,
                latency_ms=adapter_result.latency_ms,
                token_usage=adapter_result.token_usage,
                reported_cost=adapter_result.reported_cost,
                retry_count=adapter_result.retry_count,
                provider_status=adapter_result.status,
                failure_class=adapter_result.failure_class,
            )
            model_answers.append(model_answer)
            raw_by_answer[answer_id] = raw_text

            updated_claims: list[Claim] = []
            for claim in claims:
                updated_claim, verification = await self._verify_claim(
                    claim,
                    question=request.question,
                    constraints=request.constraints,
                    deadline=deadline,
                )
                updated_claims.append(updated_claim)
                if updated_claim.id:
                    verification_by_claim[updated_claim.id] = [verification]
            model_answers[-1] = model_answer.model_copy(update={"claims": updated_claims})

        if not model_answers or len(model_answers) == len(failures):
            # All adapter calls failed: no durable graph is created.
            raise NoUsableModelAnswer()

        status = "partial" if failures else "complete"
        warnings = [f"model '{model}' was unavailable" for model, _ in failures]
        if any(
            claim.verification_status == "unavailable"
            for answer in model_answers
            for claim in answer.claims
        ):
            status = "partial"
            warnings.append("one or more verifier checks were unavailable")
        question_id = uuid4()
        report_id = uuid4()
        question_summary = QuestionSummary(
            id=question_id,
            text=request.question,
            constraints=request.constraints,
            question_type=classification.question_type,
            question_type_origin=classification.origin,
            expected_output_format=request.expected_output_format,
            models=selected_models,
        )
        aggregate_constraints: dict[str, Any] = {}
        for answer in model_answers:
            for key, value in answer.constraints_check.items():
                aggregate_constraints.setdefault(key, []).append({"model": answer.model, "result": value})
        report = ReportResponse(
            report_id=report_id,
            status=status,
            cached=False,
            created_at=datetime.now(timezone.utc),
            duration_ms=(time.perf_counter() - started) * 1000,
            question=question_summary,
            recommended_answer=None,
            recommendation_message="Verification and scoring are not yet sufficient for an automated recommendation.",
            consensus=[],
            disagreements=[],
            model_comparison=model_answers,
            evidence=[],
            constraints_check=aggregate_constraints,
            warnings=warnings,
        )
        try:
            await self.store.persist_report(
                report,
                request,
                request_id=request_id,
                raw_by_answer=raw_by_answer,
                verification_by_claim=verification_by_claim,
            )
        except PersistenceError as exc:
            raise ReportPersistenceUnavailable() from exc
        return report
