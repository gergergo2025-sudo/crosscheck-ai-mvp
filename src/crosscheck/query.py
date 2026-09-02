"""Single-turn Question-to-Report orchestration for the durable tracer."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Awaitable
from uuid import UUID, uuid4

from .adapters import (
    AdapterError,
    AdapterInvocationError,
    AdapterRegistry,
    AdapterResult,
    AdapterUnavailable,
    RetryPolicy,
    call_with_retries,
)
from .classification import Classifier, resolve_classification
from .clustering import ClaimClusterer, ClusteringOutcome, NullClusterer
from .cache import NullReportCache, ReportCache, build_cache_key
from .config import Settings
from .constraints import ConstraintOutcome, ConstraintService, ReportedConstraintService
from .consensus import build_consensus_and_disagreements
from .contracts import (
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
from .parser import parse_structured_answer, parse_with_repair
from .persistence import PersistenceError, ReportStore
from .prompt import build_repair_prompt, build_unified_prompt
from .scoring import NeutralScorer, Scorer, ScoringOutcome
from .telemetry import NullTelemetry, Telemetry
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
    if isinstance(exc, AdapterInvocationError):
        return str(getattr(exc, "failure_class", "provider_error"))[:64]
    if isinstance(exc, AdapterError):
        return getattr(exc, "failure_class", "adapter_error")
    return "adapter_error"


def _merge_token_usage(
    first: dict[str, Any] | None,
    second: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Combine usage from the initial generation and bounded repair call."""

    if first is None and second is None:
        return None
    merged = dict(first or {})
    for key, value in (second or {}).items():
        previous = merged.get(key)
        if isinstance(previous, (int, float)) and isinstance(value, (int, float)) and not isinstance(previous, bool) and not isinstance(value, bool):
            merged[key] = previous + value
        elif key not in merged:
            merged[key] = value
    return merged


def _merge_adapter_results(first: AdapterResult, second: AdapterResult | None) -> AdapterResult:
    """Retain provider identity while accounting for repair-call metadata."""

    if second is None:
        return first
    return first.model_copy(
        update={
            "latency_ms": (first.latency_ms or 0.0) + (second.latency_ms or 0.0),
            "token_usage": _merge_token_usage(first.token_usage, second.token_usage),
            "reported_cost": (first.reported_cost or 0.0) + (second.reported_cost or 0.0)
            if first.reported_cost is not None or second.reported_cost is not None
            else None,
            "retry_count": first.retry_count + second.retry_count,
        }
    )


_SAFE_PROVIDER_STATUSES = {
    "ok",
    "success",
    "retryable",
    "timeout",
    "rate_limited",
    "temporarily_unavailable",
    "unavailable",
    "skipped",
    "skipped_cost_ceiling",
    "permanent",
    "error",
}
_SAFE_FAILURE_CLASSES = {
    "adapter_error",
    "adapter_unavailable",
    "unavailable",
    "timeout",
    "deadline",
    "retryable",
    "http_retryable",
    "http_permanent",
    "permanent",
    "provider_error",
    "verifier_error",
    "cost_ceiling",
}


def _safe_provider_status(value: object, *, default: str = "error") -> str:
    status = str(value or default).strip().casefold()
    return status if status in _SAFE_PROVIDER_STATUSES else default


def _safe_provider_name(value: object, fallback: str = "unknown") -> str:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 100 or not re.fullmatch(r"[A-Za-z0-9._:-]+", candidate):
        return fallback
    return candidate


def _safe_failure_value(value: object, *, default: str | None = None) -> str | None:
    if value is None:
        return default
    candidate = str(value).strip().casefold()
    if candidate in _SAFE_FAILURE_CLASSES:
        return candidate
    return default


def _sanitize_token_usage(value: object) -> dict[str, int | float] | None:
    if not isinstance(value, Mapping):
        return None
    safe: dict[str, int | float] = {}
    allowed = {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
    }
    for key, raw in value.items():
        name = str(key).strip().casefold()
        if name not in allowed:
            continue
        try:
            number = float(raw)
            if not math.isfinite(number) or number < 0:
                continue
            safe[name] = int(number) if number.is_integer() else min(number, 1_000_000_000.0)
        except (TypeError, ValueError):
            continue
    return safe or None


def _safe_http_url(value: object) -> str | None:
    """Allow only absolute HTTP(S) URLs at the public evidence boundary.

    Model-provided URLs are never fetched by the backend.  This helper only
    validates the value that may be returned to a client.
    """

    if not isinstance(value, str) or len(value) > 4_000:
        return None
    candidate = value.strip()
    match = re.match(r"^(https?)://([^\s/?#]+)(?:[^\s]*)$", candidate, re.IGNORECASE)
    if not match:
        return None
    # Reject control characters and credentials-bearing URLs.  The evidence
    # provider can still return a safe title/snippet without a clickable URL.
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in candidate) or "@" in match.group(2):
        return None
    return candidate


def _sanitize_claim(claim: Claim) -> Claim:
    source = claim.source
    if source and ("://" in source or source.strip().lower().startswith(("javascript:", "data:", "file:"))):
        source = _safe_http_url(source)
    return claim.model_copy(update={"source": source})


def _sanitize_evidence(evidence: object, *, max_count: int, max_snippet_chars: int) -> list[dict[str, Any]]:
    if not isinstance(evidence, list):
        return []
    safe: list[dict[str, Any]] = []
    for item in evidence[:max_count]:
        if not isinstance(item, Mapping):
            continue
        cleaned: dict[str, Any] = {}
        for key in ("id", "title", "domain", "publication_date", "rank", "authority", "recency", "relation"):
            value = item.get(key)
            if value is not None:
                if key in {"title", "domain", "publication_date", "relation"}:
                    cleaned[key] = str(value)[:max_snippet_chars]
                elif key in {"rank"}:
                    try:
                        cleaned[key] = max(0, min(int(value), 10_000))
                    except (TypeError, ValueError):
                        continue
                elif key in {"authority", "recency"}:
                    try:
                        number = float(value)
                        if math.isfinite(number):
                            cleaned[key] = max(0.0, min(1.0, number))
                    except (TypeError, ValueError):
                        continue
                else:
                    cleaned[key] = str(value)[:256]
        url = _safe_http_url(item.get("url"))
        if url:
            cleaned["url"] = url
        snippet = item.get("snippet")
        if snippet is not None:
            cleaned["snippet"] = str(snippet)[:max_snippet_chars]
        # Invalid URLs are omitted instead of being echoed as active-looking
        # links.  Metadata remains useful for a verifier result without any
        # outbound request.
        if cleaned:
            safe.append(cleaned)
    return safe


def _apply_cluster_ids(
    answers: list[ModelAnswer],
    clustering: ClusteringOutcome,
) -> list[ModelAnswer]:
    """Attach Cluster identity back to each Claim for traceable Consensus."""

    if not clustering.clusters:
        return answers
    cluster_by_claim = {
        claim_id: cluster.id for cluster in clustering.clusters for claim_id in cluster.claim_ids
    }
    if not cluster_by_claim:
        return answers
    return [
        answer.model_copy(
            update={
                "claims": [
                    claim.model_copy(update={"cluster_id": cluster_by_claim.get(claim.id, claim.cluster_id)})
                    for claim in answer.claims
                ]
            }
        )
        for answer in answers
    ]


def _degraded_answer(*, answer_id: UUID, model: str, provider: str, diagnostics: list[str],
                     provider_status: str, failure_class: str | None, retry_count: int = 0,
                     answer: str = "Provider did not return an answer.", result: AdapterResult | None = None) -> ModelAnswer:
    """Build one consistent fail-closed ModelAnswer for every degraded path."""
    return ModelAnswer(
        id=answer_id, model=model, provider=provider, answer=answer, reasoning="", claims=[],
        constraints_check={}, parse_status="degraded", parse_diagnostics=diagnostics, score=0.0,
        latency_ms=result.latency_ms if result else None,
        token_usage=_sanitize_token_usage(result.token_usage) if result else None,
        reported_cost=result.reported_cost if result else None,
        retry_count=max(0, retry_count), provider_status=provider_status,
        failure_class=_safe_failure_value(failure_class, default="provider_error" if failure_class else None),
    )


def _is_high_compliance(question: str) -> bool:
    normalized = question.casefold()
    terms = (
        "medical", "medicine", "diagnos", "treatment", "symptom", "doctor", "health", "医疗", "诊断", "治疗", "症状",
        "legal", "lawyer", "lawsuit", "contract law", "法律", "诉讼", "律师",
        "financial advice", "invest", "stock", "loan", "mortgage", "保险", "投资", "股票", "贷款",
    )
    return any(term in normalized for term in terms)


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
        clusterer: ClaimClusterer | None = None,
        scorer: Scorer | None = None,
        constraint_service: ConstraintService | None = None,
        cache: ReportCache | None = None,
        telemetry: Telemetry | None = None,
        clock: Any | None = None,
        sleeper: Any | None = None,
        random_fn: Any | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.adapters = adapters
        self.verifiers = verifiers or VerifierRegistry()
        self.classifier = classifier
        # Pipeline stages are ports so clustering, verification, scoring, cache and
        # telemetry behaviour can be replaced without touching orchestration.
        self.clusterer = clusterer or NullClusterer()
        self.scorer = scorer or NeutralScorer()
        self.constraint_service = constraint_service or ReportedConstraintService()
        self.cache = cache or NullReportCache()
        self.telemetry = telemetry or NullTelemetry()
        # Ports are injectable for deterministic fake-clock/provider contract
        # tests.  ``clock`` may be a callable or an object exposing ``monotonic``.
        self.clock = clock if callable(clock) else getattr(clock, "monotonic", time.monotonic)
        self.sleeper = sleeper or asyncio.sleep
        self.random_fn = random_fn

    def behaviour_versions(self) -> dict[str, Any]:
        """Return every behaviour version that must participate in the cache key."""

        return {
            "prompt": self.settings.prompt_version,
            "adapters": getattr(self.adapters, "configuration_version", "1"),
            "adapter_runtime": {
                "attempt_timeout": self.settings.adapter_attempt_timeout_seconds,
                "max_retries": self.settings.adapter_max_retries,
                "backoff": [self.settings.retry_backoff_base_seconds, self.settings.retry_backoff_max_seconds],
                "max_raw_chars": self.settings.max_raw_response_chars,
                "cost_ceiling": self.settings.max_query_cost_usd,
                "cost_estimates": dict(sorted(self.settings.model_cost_estimates.items())),
                "openai_base_url": self.settings.openai_base_url,
                "anthropic_base_url": self.settings.anthropic_base_url,
                "deepseek_base_url": self.settings.deepseek_base_url,
            },
            "clustering": {
                "method": getattr(self.clusterer, "method", "none"),
                "version": getattr(self.clusterer, "version", "0"),
                "threshold": getattr(self.clusterer, "threshold", None),
                "lexical_threshold": getattr(self.clusterer, "lexical_threshold", None),
                "embedding": getattr(getattr(self.clusterer, "embedder", None), "version", "none"),
            },
            "verifiers": {
                "versions": getattr(self.verifiers, "version_set", lambda: "none")(),
                "tavily_results": self.settings.tavily_max_results,
                "sandbox_image": self.settings.sandbox_image,
                "sandbox_timeout": self.settings.sandbox_timeout_seconds,
            },
            "scoring": getattr(self.scorer, "version", "0"),
            "constraints": getattr(self.constraint_service, "version", "reported-v1"),
        }

    async def _cluster_claims(
        self,
        answers: list[ModelAnswer],
        *,
        deadline: float,
    ) -> ClusteringOutcome:
        """Cluster Claims without letting a clustering failure fail the Report."""

        try:
            outcome = await asyncio.wait_for(
                self.clusterer.cluster(answers, deadline=deadline),
                timeout=max(0.001, deadline - self.clock()),
            )
        except asyncio.CancelledError:
            raise
        except BaseException:
            return ClusteringOutcome(
                method="unavailable",
                degraded=True,
                warnings=["claim clustering was unavailable; consensus grouping is degraded"],
            )
        self.telemetry.emit(
            "clustering.completed",
            method=outcome.method,
            version=outcome.version,
            threshold=outcome.threshold,
            degraded=outcome.degraded,
            cluster_count=len(outcome.clusters),
        )
        return outcome

    async def _check_constraints(
        self,
        request: QueryRequest,
        answers: list[ModelAnswer],
        *,
        deadline: float,
    ) -> ConstraintOutcome:
        """Run per-Constraint verification without failing the whole Report."""

        try:
            outcome = await asyncio.wait_for(
                self.constraint_service.check(request, answers, deadline=deadline),
                timeout=max(0.001, deadline - self.clock()),
            )
        except asyncio.CancelledError:
            raise
        except BaseException:
            return ConstraintOutcome(
                warnings=["constraint verification was unavailable"],
            )
        self.telemetry.emit("constraints.completed", constraint_count=len(outcome.aggregate))
        return outcome

    def _retry_policy(self) -> RetryPolicy:        return RetryPolicy(
            attempt_timeout_seconds=self.settings.adapter_attempt_timeout_seconds,
            max_retries=self.settings.adapter_max_retries,
            backoff_base_seconds=self.settings.retry_backoff_base_seconds,
            backoff_max_seconds=self.settings.retry_backoff_max_seconds,
            jitter_seconds=self.settings.retry_jitter_seconds,
            retry_after_max_seconds=self.settings.retry_after_max_seconds,
        )

    def _selected_models(self, request: QueryRequest) -> list[str]:
        selected = request.models or self.settings.configured_models()
        if not selected:
            raise ModelConfigurationUnavailable()
        if len(selected) > self.settings.max_model_count:
            raise RequestValidationError(
                "too many models requested",
                details={"models": [f"maximum {self.settings.max_model_count} models"]},
            )
        oversized = [model for model in selected if len(model) > self.settings.max_model_name_length]
        if oversized:
            raise RequestValidationError(
                "one or more model identifiers are too long",
                details={"models": ["model identifier exceeds maximum length"]},
            )
        # ``AdapterRegistry`` is the runtime allow-list.  If settings explicitly
        # declare an allow-list, a request cannot reach an injected adapter that an
        # operator did not publish.
        configured = self.settings.configured_models()
        # In-process test/deployment adapters are themselves an allow-list.  A
        # settings allow-list is additionally authoritative only when the operator
        # supplied ``CROSSCHECK_ALLOWED_MODELS`` explicitly; this keeps injected
        # adapter registries usable without weakening the public runtime default.
        settings_allowlist = bool(self.settings.allowed_models and self.settings.allowed_models.strip())
        if request.models and settings_allowlist and any(model not in configured for model in selected):
            unknown = [model for model in selected if model not in configured]
            raise RequestValidationError(
                "one or more requested models are not allow-listed",
                details={"models": unknown},
            )
        known = self.adapters.known_models()
        unknown = [model for model in selected if model not in known]
        # Explicit unknown identifiers are client mistakes.  A missing adapter in
        # the server's configured default set is instead treated as an unavailable
        # sibling so one configured provider can still produce a truthful partial
        # report.
        if unknown and request.models is not None:
            raise RequestValidationError(
                "one or more requested models are not allow-listed",
                details={"models": unknown},
            )
        if not self.adapters.usable_models().intersection(selected):
            raise ModelConfigurationUnavailable()
        return selected

    def _estimate_cost(self, model: str, adapter: Any, prompt: str) -> float | None:
        """Read only operator/configured cost estimates, never provider secrets."""

        configured = self.settings.model_cost_estimates.get(model)
        if configured is not None:
            try:
                value = float(configured)
                return value if math.isfinite(value) and value >= 0 else None
            except (TypeError, ValueError):
                return None
        for name in ("estimated_cost_usd", "estimated_cost"):
            value = getattr(adapter, name, None)
            if callable(value):
                try:
                    value = value(prompt=prompt, model=model)
                except TypeError:
                    try:
                        value = value(prompt, model)
                    except Exception:
                        value = None
                except Exception:
                    value = None
            if value is not None:
                try:
                    parsed = float(value)
                    return parsed if math.isfinite(parsed) and parsed >= 0 else None
                except (TypeError, ValueError):
                    pass
        return None

    def _provider_name(self, model: str) -> str:
        try:
            return str(getattr(self.adapters.get(model), "provider", "unknown"))[:100] or "unknown"
        except Exception:
            return "unknown"

    async def _call_adapter(
        self,
        model: str,
        prompt: str,
        *,
        deadline: float,
    ) -> tuple[str, AdapterResult | None, BaseException | None]:
        adapter = self.adapters.get(model)
        try:
            result = await call_with_retries(
                adapter,
                prompt,
                model=model,
                deadline=deadline,
                policy=self._retry_policy(),
                clock=self.clock,
                sleeper=self.sleeper,
                random_fn=self.random_fn or __import__("random").random,
            )
            return model, _adapter_result(result, model=model), None
        except asyncio.TimeoutError as exc:
            return model, None, AdapterInvocationError(
                "timeout",
                provider=self._provider_name(model),
            )
        except AdapterInvocationError as exc:
            return model, None, exc
        except AdapterUnavailable as exc:
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
            remaining = max(0.001, deadline - self.clock())
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
        except asyncio.CancelledError:
            raise
        except BaseException:
            result = VerificationResult(status="unavailable", failure_class="verifier_error", details={"reason": "verifier failed"})
        evidence = _sanitize_evidence(result.evidence, max_count=self.settings.max_evidence_count,
                                      max_snippet_chars=self.settings.max_evidence_snippet_chars)
        evidence_ids: list[UUID] = []
        normalized_evidence: list[dict[str, Any]] = []
        for item in evidence:
            try:
                evidence_id = UUID(str(item.get("id")))
            except (ValueError, TypeError, AttributeError):
                evidence_id = uuid4()
            evidence_ids.append(evidence_id)
            normalized_evidence.append({**item, "id": str(evidence_id)})
        verification_id = result.id or uuid4()
        result = result.model_copy(update={"id": verification_id, "evidence": normalized_evidence})
        updated = claim.model_copy(
            update={
                "verification_status": result.status,
                "verification_confidence": result.confidence,
                "verification_ids": [verification_id],
                "evidence_ids": evidence_ids,
            }
        )
        self.telemetry.emit("verifier.completed", verifier=result.verifier_type, status=result.status, duration_ms=result.duration_ms)
        return updated, result

    async def _fan_out_adapters(
        self,
        models: list[str],
        prompt: str,
        *,
        deadline: float,
        budget: dict[str, float] | None = None,
    ) -> list[tuple[str, AdapterResult | None, BaseException | None]]:
        """Dispatch bounded provider work concurrently and isolate siblings."""

        dispatch: list[str] = []
        skipped: list[tuple[str, AdapterResult | None, BaseException | None]] = []
        budget = budget if budget is not None else {"reserved": 0.0, "reported": 0.0}
        ceiling = self.settings.max_query_cost_usd
        for model in models:
            try:
                adapter = self.adapters.get(model)
            except AdapterUnavailable as exc:
                skipped.append((model, None, exc))
                continue
            estimate = self._estimate_cost(model, adapter, prompt)
            if ceiling is not None and estimate is not None:
                if budget["reserved"] + estimate > ceiling + 1e-12:
                    skipped.append(
                        (
                            model,
                            None,
                            AdapterInvocationError(
                                "cost_ceiling",
                                provider=self._provider_name(model),
                            ),
                        )
                    )
                    continue
                budget["reserved"] += estimate
            dispatch.append(model)

        tasks = {
            model: asyncio.create_task(self._call_adapter(model, prompt, deadline=deadline))
            for model in dispatch
        }
        if not tasks:
            return skipped
        timeout = max(0.0, deadline - self.clock())
        done, pending = await asyncio.wait(tuple(tasks.values()), timeout=timeout)
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        by_task: dict[asyncio.Task[Any], tuple[str, AdapterResult | None, BaseException | None]] = {}
        for model, task in tasks.items():
            if task in done:
                try:
                    by_task[task] = task.result()
                except asyncio.CancelledError:
                    by_task[task] = (
                        model,
                        None,
                        AdapterInvocationError("deadline", provider=self._provider_name(model)),
                    )
                except BaseException as exc:
                    by_task[task] = (model, None, exc)
            else:
                by_task[task] = (
                    model,
                    None,
                    AdapterInvocationError("deadline", provider=self._provider_name(model)),
                )
        # Preserve configured model order, which also makes tie/error rendering
        # deterministic for clients and tests.
        by_model = {model: by_task[tasks[model]] for model in dispatch}
        by_model.update({item[0]: item for item in skipped})
        ordered = [by_model[model] for model in models]
        for model, result, failure in ordered:
            if result:
                budget["reported"] += float(result.reported_cost or 0.0)
                self.telemetry.emit("adapter.completed", model=model, provider=result.provider, status=result.status,
                                    retry_count=result.retry_count, latency_ms=result.latency_ms,
                                    token_count=(result.token_usage or {}).get("total_tokens"), reported_cost=result.reported_cost)
                if result.retry_count:
                    self.telemetry.emit("adapter.retry", model=model, provider=result.provider, retry_count=result.retry_count)
            else:
                self.telemetry.emit("adapter.completed", model=model, provider=self._provider_name(model), status="unavailable",
                                    retry_count=getattr(failure, "retry_count", 0))
        return ordered

    async def _verify_claims(
        self,
        model_answers: list[ModelAnswer],
        *,
        clustering: ClusteringOutcome,
        question: str,
        constraints: dict[str, Any] | str | None,
        deadline: float,
    ) -> tuple[list[ModelAnswer], dict[UUID, list[VerificationResult]]]:
        claims = {claim.id: claim for answer in model_answers if answer.parse_status == "parsed" for claim in answer.claims if claim.id}
        representative_ids = [cluster.representative_claim_id for cluster in clustering.clusters if cluster.representative_claim_id]
        clustered_ids = {claim_id for cluster in clustering.clusters for claim_id in cluster.claim_ids}
        representative_ids.extend(claim_id for claim_id in claims if claim_id not in clustered_ids)
        jobs = {
            asyncio.create_task(self._verify_claim(claims[claim_id], question=question, constraints=constraints, deadline=deadline)): claim_id
            for claim_id in representative_ids if claim_id in claims
        }
        if not jobs:
            return model_answers, {}
        done, pending = await asyncio.wait(tuple(jobs), timeout=max(0.0, deadline - self.clock()))
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        representative_results: dict[UUID, tuple[Claim, VerificationResult]] = {}
        for task, claim_id in jobs.items():
            if task in done:
                try:
                    representative_results[claim_id] = task.result()
                except BaseException:
                    result = VerificationResult(id=uuid4(), status="unavailable", failure_class="verifier_error")
                    representative_results[claim_id] = (claims[claim_id].model_copy(update={"verification_status": "unavailable", "verification_ids": [result.id]}), result)
            else:
                result = VerificationResult(id=uuid4(), status="unavailable", failure_class="deadline")
                representative_results[claim_id] = (claims[claim_id].model_copy(update={"verification_status": "unavailable", "verification_ids": [result.id]}), result)

        representative_for_claim = {claim_id: cluster.representative_claim_id for cluster in clustering.clusters for claim_id in cluster.claim_ids}
        verification_by_claim: dict[UUID, list[VerificationResult]] = {}
        updated_answers: list[ModelAnswer] = []
        for answer in model_answers:
            updated_claims: list[Claim] = []
            for claim in answer.claims:
                if not claim.id:
                    updated_claims.append(claim)
                    continue
                representative_id = representative_for_claim.get(claim.id, claim.id)
                representative_claim, base_result = representative_results[representative_id]
                if claim.id == representative_id:
                    updated_claim, result = representative_claim, base_result
                else:
                    result = base_result.model_copy(update={"id": uuid4(), "details": {**base_result.details, "representative_claim_id": str(representative_id)}})
                    updated_claim = claim.model_copy(update={
                        "verification_status": result.status, "verification_confidence": result.confidence,
                        "verification_ids": [result.id],
                        "evidence_ids": [UUID(str(item["id"])) for item in result.evidence if item.get("id")],
                    })
                verification_by_claim[claim.id] = [result]
                updated_claims.append(updated_claim)
            updated_answers.append(answer.model_copy(update={"claims": updated_claims}))
        for cluster in clustering.clusters:
            result = verification_by_claim.get(cluster.representative_claim_id, [None])[0]
            if result:
                cluster.verification_status = result.status
                cluster.verification_confidence = result.confidence
        return updated_answers, verification_by_claim

    async def execute(self, request: QueryRequest, *, request_id: UUID | None = None) -> ReportResponse:
        started = time.perf_counter()
        request_id = request_id or uuid4()
        if len(request.question) > self.settings.max_question_length:
            raise RequestValidationError(
                "question is too long",
                details={"question": ["maximum length exceeded"]},
            )
        if isinstance(request.constraints, str) and len(request.constraints) > self.settings.max_constraints_length:
            raise RequestValidationError(
                "constraints are too long",
                details={"constraints": ["maximum length exceeded"]},
            )
        if isinstance(request.constraints, dict):
            try:
                constraints_size = len(json.dumps(request.constraints, ensure_ascii=False, default=str))
            except (TypeError, ValueError, RecursionError):
                raise RequestValidationError(
                    "constraints are invalid",
                    details={"constraints": ["could not normalize constraints"]},
                ) from None
            if constraints_size > self.settings.max_constraints_length:
                raise RequestValidationError(
                    "constraints are too long",
                    details={"constraints": ["maximum length exceeded"]},
                )
        selected_models = self._selected_models(request)
        deadline = self.clock() + self.settings.query_deadline_seconds
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
        cache_key = build_cache_key(
            request,
            models=selected_models,
            question_type=classification.question_type,
            versions=self.behaviour_versions(),
        )
        self.telemetry.emit(
            "query.started",
            request_id=str(request_id),
            question_type=classification.question_type,
            question_type_origin=classification.origin,
            model_count=len(selected_models),
            question_length=len(request.question),
        )
        if not request.refresh:
            cached = await self.cache.get(cache_key)
            if self.cache.warnings():
                self.telemetry.emit("cache.error", request_id=str(request_id), outcome="degraded")
            if cached is not None:
                self.telemetry.emit("cache.hit", request_id=str(request_id), report_id=str(cached.report_id))
                return cached.model_copy(update={"cached": True})
            self.telemetry.emit("cache.miss", request_id=str(request_id))
        lock_token: str | None = None
        acquire_lock = getattr(self.cache, "acquire_lock", None)
        if callable(acquire_lock):
            lock_token = await acquire_lock(cache_key)
            if lock_token is None:
                # A lock miss means another identical query owns provider
                # fan-out. Wait for its committed Report, or take ownership if
                # its lock expires/fails, instead of duplicating paid work after
                # an arbitrary 250 ms polling window.
                while self.clock() < deadline:
                    await self.sleeper(min(0.05, max(0.0, deadline - self.clock())))
                    cached = await self.cache.get(cache_key)
                    if cached is not None and not request.refresh:
                        self.telemetry.emit("cache.hit", request_id=str(request_id), report_id=str(cached.report_id))
                        return cached.model_copy(update={"cached": True})
                    lock_token = await acquire_lock(cache_key)
                    if lock_token is not None:
                        break
                if lock_token is None:
                    raise NoUsableModelAnswer()

        cost_budget = {"reserved": 0.0, "reported": 0.0}
        results = await self._fan_out_adapters(selected_models, prompt, deadline=deadline, budget=cost_budget)
        model_answers: list[ModelAnswer] = []
        raw_by_answer: dict[UUID, str] = {}
        failures: list[tuple[str, BaseException]] = []
        degraded_models: list[str] = []
        # A provider that returned text produces a Report entry even when its
        # structured output could not be repaired; only providers that never
        # answered are excluded from the Report.
        responded_answer_ids: set[UUID] = set()
        verification_by_claim: dict[UUID, list[VerificationResult]] = {}
        reported_cost = 0.0

        for model, adapter_result, failure in results:
            answer_id = uuid4()
            if failure is not None or adapter_result is None:
                assert failure is not None
                failures.append((model, failure))
                provider = _safe_provider_name(
                    getattr(failure, "provider", None),
                    _safe_provider_name(self._provider_name(model)),
                )
                failure_class = _safe_failure_class(failure)
                status = "skipped_cost_ceiling" if failure_class == "cost_ceiling" else (
                    "timeout" if failure_class in {"deadline", "timeout"} else "unavailable"
                )
                model_answers.append(_degraded_answer(answer_id=answer_id, model=model, provider=provider,
                    diagnostics=["provider call did not produce a usable result"], provider_status=status,
                    failure_class=failure_class, retry_count=int(getattr(failure, "retry_count", 0))))
                degraded_models.append(model)
                continue

            raw_text = _bounded_text(adapter_result.raw_text, self.settings.max_raw_response_chars)
            provider = _safe_provider_name(
                adapter_result.provider,
                _safe_provider_name(self._provider_name(model)),
            )
            provider_status = _safe_provider_status(adapter_result.status)
            # A result status that explicitly denotes failure is not allowed to
            # become a successful parsed answer merely because a provider returned
            # an empty/partial body.
            if not raw_text.strip() and provider_status != "ok":
                failure = AdapterInvocationError(
                    adapter_result.failure_class or provider_status,
                    provider=provider,
                    retry_count=adapter_result.retry_count,
                )
                failures.append((model, failure))
                model_answers.append(_degraded_answer(answer_id=answer_id, model=model, provider=provider,
                    diagnostics=["provider returned no answer text"], provider_status=provider_status,
                    failure_class=_safe_failure_class(failure), retry_count=adapter_result.retry_count, result=adapter_result))
                degraded_models.append(model)
                continue

            repair_result: AdapterResult | None = None
            repair_failure: BaseException | None = None

            async def repair_response(invalid_response: str) -> str:
                nonlocal repair_result, repair_failure
                repair_prompt = build_repair_prompt(
                    invalid_response,
                    original_prompt=prompt,
                    version=self.settings.prompt_version,
                    max_chars=min(self.settings.max_raw_response_chars, 30_000),
                )
                adapter = self.adapters.get(model)
                estimate = self._estimate_cost(model, adapter, repair_prompt)
                ceiling = self.settings.max_query_cost_usd
                if ceiling is not None and (
                    cost_budget["reported"] >= ceiling - 1e-12
                    or (estimate is not None and cost_budget["reserved"] + estimate > ceiling + 1e-12)
                ):
                    repair_failure = AdapterInvocationError("cost_ceiling", provider=provider)
                    raise repair_failure
                if estimate is not None:
                    cost_budget["reserved"] += estimate
                _, repair_result, repair_failure = await self._call_adapter(
                    model,
                    repair_prompt,
                    deadline=deadline,
                )
                if repair_failure is not None or repair_result is None:
                    raise repair_failure or RuntimeError("repair did not return a response")
                cost_budget["reported"] += float(repair_result.reported_cost or 0.0)
                self.telemetry.emit("adapter.repair_completed", model=model, provider=repair_result.provider,
                                    status=repair_result.status, retry_count=repair_result.retry_count,
                                    latency_ms=repair_result.latency_ms, reported_cost=repair_result.reported_cost)
                if repair_result.retry_count:
                    self.telemetry.emit("adapter.retry", model=model, provider=repair_result.provider, retry_count=repair_result.retry_count)
                return _bounded_text(repair_result.raw_text, self.settings.max_raw_response_chars)

            # Parse the adapter-contract-bounded response before applying the
            # tighter persistence/repair-prompt cap. This avoids turning a valid
            # response into malformed JSON solely because audit storage is small.
            parsed = parse_structured_answer(adapter_result.raw_text, max_chars=120_000)
            if not parsed.parse_success:
                parsed = await parse_with_repair(raw_text, repair_response, max_chars=self.settings.max_raw_response_chars)
            effective_result = _merge_adapter_results(adapter_result, repair_result)
            reported_cost += float(effective_result.reported_cost or 0.0)
            self.telemetry.emit("parse.completed", model=model, parse_status=parsed.parse_status,
                                repair_attempted=parsed.repair_attempted, repair_succeeded=parsed.repair_succeeded)
            if parsed.structured is None:
                model_answer = _degraded_answer(answer_id=answer_id, model=model, provider=provider,
                    answer=_bounded_text(raw_text or "No answer text was returned.", 100_000),
                    diagnostics=parsed.diagnostics, provider_status=provider_status,
                    failure_class=adapter_result.failure_class or (_safe_failure_class(repair_failure) if repair_failure else None),
                    retry_count=effective_result.retry_count, result=effective_result)
                model_answers.append(model_answer)
                raw_by_answer[answer_id] = raw_text
                degraded_models.append(model)
                responded_answer_ids.add(answer_id)
                continue

            claims = [
                _sanitize_claim(claim.model_copy(update={"id": uuid4()}))
                for claim in parsed.structured.claims
            ]
            model_answer = ModelAnswer(
                id=answer_id,
                model=model,
                provider=provider,
                answer=parsed.structured.answer,
                reasoning=parsed.structured.reasoning,
                claims=claims,
                constraints_check=parsed.structured.constraints_check,
                parse_status="parsed",
                parse_diagnostics=parsed.diagnostics,
                score=0.0,
                latency_ms=effective_result.latency_ms,
                token_usage=_sanitize_token_usage(effective_result.token_usage),
                reported_cost=effective_result.reported_cost,
                retry_count=effective_result.retry_count,
                provider_status=provider_status,
                failure_class=_safe_failure_value(adapter_result.failure_class),
            )
            model_answers.append(model_answer)
            raw_by_answer[answer_id] = raw_text
            responded_answer_ids.add(answer_id)

        usable_answers = [answer for answer in model_answers if answer.parse_status == "parsed" and answer.answer.strip()]
        if not usable_answers:
            release_lock = getattr(self.cache, "release_lock", None)
            if lock_token and callable(release_lock):
                await release_lock(cache_key, lock_token)
            raise NoUsableModelAnswer()

        clustering = await self._cluster_claims(model_answers, deadline=deadline)
        model_answers = _apply_cluster_ids(model_answers, clustering)
        model_answers, verification_by_claim = await self._verify_claims(
            model_answers, clustering=clustering,
            question=request.question,
            constraints=request.constraints,
            deadline=deadline,
        )
        constraint_outcome = await self._check_constraints(request, model_answers, deadline=deadline)
        model_answers = [answer.model_copy(update={"constraints_check": {
            item["constraint"]: item for item in constraint_outcome.per_answer.get(answer.id, [])
        }}) for answer in model_answers]
        consensus, disagreements = build_consensus_and_disagreements(
            model_answers,
            clustering=clustering,
            verification_by_claim=verification_by_claim,
        )
        scoring = self.scorer.score(
            model_answers,
            clustering=clustering,
            verification_by_claim=verification_by_claim,
            constraint_results=constraint_outcome.per_answer,
            usable_provider_count=len({answer.provider for answer in usable_answers}),
        )
        model_answers = [
            answer.model_copy(
                update={
                    "score": scoring.scores.get(answer.id, 0.0),
                    "score_components": scoring.components.get(answer.id, {}),
                }
            )
            for answer in model_answers
        ]
        recommended_answer = next(
            (answer for answer in model_answers if answer.id == scoring.recommended_answer_id),
            None,
        )
        evidence_only = _is_high_compliance(request.question)
        if evidence_only:
            recommended_answer = None
            scoring.recommendation_message = "Evidence-only report: automated decision endorsement is suppressed for high-compliance topics."
        status = "partial" if failures or degraded_models else "complete"
        warnings: list[str] = []
        for model, failure in failures:
            failure_class = _safe_failure_class(failure)
            if failure_class == "cost_ceiling":
                warnings.append(f"model '{model}' was skipped by the configured cost ceiling")
            elif failure_class in {"deadline", "timeout"}:
                warnings.append(f"model '{model}' timed out before returning an answer")
            else:
                warnings.append(f"model '{model}' was unavailable")
        if degraded_models:
            warnings.extend(
                f"model '{model}' returned an unparseable structured answer; shown as degraded"
                for model in degraded_models
            )
        warnings.extend(clustering.warnings)
        warnings.extend(constraint_outcome.warnings)
        warnings.extend(scoring.warnings)
        warnings.extend(self.cache.warnings())
        if self.settings.max_query_cost_usd is not None and reported_cost > self.settings.max_query_cost_usd:
            warnings.append("reported provider usage exceeded the configured cost ceiling")
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
        all_evidence: list[dict[str, Any]] = []
        for answer in model_answers:
            for claim in answer.claims:
                for verification in verification_by_claim.get(claim.id, []):
                    all_evidence.extend(verification.evidence)
        evidence = _sanitize_evidence(
            list({str(item.get("id") or (item.get("url"), item.get("title"))): item for item in all_evidence}.values()),
            max_count=self.settings.max_evidence_count,
            max_snippet_chars=self.settings.max_evidence_snippet_chars,
        )
        report = ReportResponse(
            report_id=report_id,
            status=status,
            cached=False,
            created_at=datetime.now(timezone.utc),
            duration_ms=(time.perf_counter() - started) * 1000,
            question=question_summary,
            recommended_answer=recommended_answer,
            recommendation_message=scoring.recommendation_message,
            consensus=consensus,
            disagreements=disagreements,
            model_comparison=model_answers,
            evidence=evidence,
            constraints_check=constraint_outcome.aggregate,
            warnings=warnings,
            behavior_versions=self.behaviour_versions(),
            cache_key_version="cachekey-v1",
            evidence_only=evidence_only,
        )
        try:
            await self.store.persist_report(
                report,
                request,
                request_id=request_id,
                raw_by_answer=raw_by_answer,
                verification_by_claim=verification_by_claim,
                clusters=clustering,
                cache_key=cache_key,
                cache_key_version="cachekey-v1",
            )
        except PersistenceError as exc:
            raise ReportPersistenceUnavailable() from exc
        await self.cache.set(cache_key, report)
        if self.cache.warnings():
            self.telemetry.emit("cache.error", request_id=str(request_id), report_id=str(report_id), outcome="degraded")
        release_lock = getattr(self.cache, "release_lock", None)
        if lock_token and callable(release_lock):
            await release_lock(cache_key, lock_token)
        self.telemetry.emit("persistence.completed", request_id=str(request_id), report_id=str(report_id), status="committed")
        self.telemetry.emit("scoring.completed", request_id=str(request_id), report_id=str(report_id), score=max(scoring.scores.values(), default=0.0))
        self.telemetry.emit(
            "query.completed",
            request_id=str(request_id),
            report_id=str(report_id),
            status=status,
            cached=False,
            duration_ms=report.duration_ms,
            model_count=len(model_answers),
            usable_model_count=len(usable_answers),
        )
        return report
