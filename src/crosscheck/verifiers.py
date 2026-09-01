"""Provider-neutral Verifier ports for the durable tracer."""

from __future__ import annotations

import time
from typing import Any, Mapping, Protocol

from .contracts import Claim, VerificationResult


class Verifier(Protocol):
    verifier_type: str

    async def verify(
        self,
        claim: Claim,
        *,
        question: str,
        constraints: dict[str, Any] | str | None,
        deadline: float | None = None,
    ) -> VerificationResult:
        """Return a data result; verifier failures must not leak as raw exceptions."""


class DeterministicVerifier:
    """Safe default verifier which reports uncertainty without external calls."""

    verifier_type = "deterministic"
    verifier_version = "1"

    async def verify(
        self,
        claim: Claim,
        *,
        question: str,
        constraints: dict[str, Any] | str | None,
        deadline: float | None = None,
    ) -> VerificationResult:
        del question, constraints, deadline
        started = time.perf_counter()
        if claim.type in {"math", "logic", "opinion", "recommendation"}:
            status = "not_applicable"
            details = {"reason": "no independent verifier is registered for this claim type"}
        else:
            status = "unverified"
            details = {"reason": "deterministic tracer verifier has no external evidence source"}
        return VerificationResult(
            verifier_type=self.verifier_type,
            verifier_version=self.verifier_version,
            status=status,
            confidence=0.0,
            details=details,
            duration_ms=(time.perf_counter() - started) * 1000,
        )


class VerifierRegistry:
    """Map claim type to the registered Verifier without exposing implementation types."""

    def __init__(self, verifiers: Mapping[str, Verifier] | None = None) -> None:
        self._verifiers = dict(verifiers or {})

    def register(self, claim_type: str, verifier: Verifier) -> None:
        self._verifiers[claim_type] = verifier

    def get(self, claim_type: str) -> Verifier:
        return self._verifiers.get("*") or self._verifiers.get(claim_type) or DeterministicVerifier()


class StaticVerifier:
    """Tiny injectable verifier useful for deterministic HTTP acceptance fixtures."""

    def __init__(self, result: VerificationResult | None = None) -> None:
        self.result = result or VerificationResult(status="verified", confidence=1.0)
        self.calls: list[str] = []
        self.verifier_type = self.result.verifier_type

    async def verify(
        self,
        claim: Claim,
        *,
        question: str,
        constraints: dict[str, Any] | str | None,
        deadline: float | None = None,
    ) -> VerificationResult:
        del question, constraints, deadline
        self.calls.append(claim.claim)
        return self.result.model_copy(deep=True)
