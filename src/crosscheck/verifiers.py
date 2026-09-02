"""Provider-neutral Verifier ports for the durable tracer."""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
from typing import Any, Mapping, Protocol
from uuid import uuid4

import httpx

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

    def version_set(self) -> str:
        return "|".join(
            f"{claim_type}:{getattr(verifier, 'verifier_type', 'unknown')}:{getattr(verifier, 'verifier_version', '1')}"
            for claim_type, verifier in sorted(self._verifiers.items())
        ) or "deterministic:1"


class FactVerifier:
    verifier_type = "fact"
    verifier_version = "tavily-v1"

    def __init__(self, api_key: str, *, max_results: int = 5, http_client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self.max_results = max(5, min(10, max_results))
        self.http_client = http_client

    async def verify(self, claim: Claim, *, question: str, constraints: dict[str, Any] | str | None,
                     deadline: float | None = None) -> VerificationResult:
        del question, constraints
        started = time.perf_counter()
        timeout = 8.0 if deadline is None else max(0.001, min(8.0, deadline - time.monotonic()))
        client = self.http_client or httpx.AsyncClient()
        owned = self.http_client is None
        try:
            response = await client.post("https://api.tavily.com/search", json={"api_key": self.api_key, "query": claim.claim, "max_results": self.max_results}, timeout=timeout)
            response.raise_for_status()
            rows = response.json().get("results", [])[: self.max_results]
        except Exception:
            return VerificationResult(verifier_type=self.verifier_type, verifier_version=self.verifier_version, status="unavailable", confidence=0, failure_class="verifier_error", details={"reason": "search provider unavailable"})
        finally:
            if owned:
                await client.aclose()
        claim_tokens = set(re.findall(r"\w+", claim.claim.casefold()))
        evidence: list[dict[str, Any]] = []
        support_scores: list[float] = []
        for rank, row in enumerate(rows, 1):
            if not isinstance(row, Mapping):
                continue
            text_value = f"{row.get('title', '')} {row.get('content', '')}"
            result_tokens = set(re.findall(r"\w+", text_value.casefold()))
            relation = len(claim_tokens & result_tokens) / max(1, len(claim_tokens))
            url = str(row.get("url", ""))
            domain = re.sub(r"^www\.", "", url.split("/")[2] if "://" in url else "")
            authority = .9 if domain.endswith((".gov", ".edu")) or any(name in domain for name in ("reuters", "apnews", "nature.com", "science.org", "bbc.")) else .55
            evidence.append({"id": str(uuid4()), "url": row.get("url"), "title": row.get("title"), "snippet": str(row.get("content", ""))[:1000], "domain": domain, "rank": rank, "authority": authority, "relation": "supporting" if relation >= .55 else "context"})
            if relation >= .55:
                support_scores.append((relation + authority) / 2)
        status = "verified" if support_scores else "unverified"
        confidence = min(1.0, sum(support_scores) / len(support_scores)) if support_scores else 0.0
        return VerificationResult(verifier_type=self.verifier_type, verifier_version=self.verifier_version, status=status, confidence=confidence, evidence=evidence, details={"result_count": len(evidence), "support_count": len(support_scores)}, duration_ms=(time.perf_counter() - started) * 1000)


class CodeVerifier:
    verifier_type = "code"
    verifier_version = "docker-python-v1"

    def __init__(self, image: str, *, timeout_seconds: float = 5.0) -> None:
        self.image = image
        self.timeout_seconds = timeout_seconds

    async def verify(self, claim: Claim, *, question: str, constraints: dict[str, Any] | str | None,
                     deadline: float | None = None) -> VerificationResult:
        del constraints, deadline
        code_match = re.search(r"```(?:python)?\s*(.*?)```", claim.claim, re.I | re.S)
        test_blocks = re.findall(r"```(?:python)?\s*(.*?)```", question, re.I | re.S)
        if not code_match or not test_blocks:
            return VerificationResult(verifier_type=self.verifier_type, verifier_version=self.verifier_version, status="unverified", details={"reason": "clearly delimited Python code and explicit tests are required"})
        script = code_match.group(1) + "\n\n" + test_blocks[-1]

        def run() -> subprocess.CompletedProcess[str]:
            # Stream the bounded program over stdin. When the backend uses the
            # host Docker socket, host-path bind mounts would incorrectly refer
            # to the daemon host rather than this container's temporary files.
            return subprocess.run([
                "docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--memory=128m", "--cpus=.5", "--pids-limit=64",
                "--user=65534:65534", self.image, "python", "-I", "-B", "-",
            ], input=script, capture_output=True, text=True, timeout=self.timeout_seconds, check=False)
        started = time.perf_counter()
        try:
            process = await asyncio.to_thread(run)
        except (OSError, subprocess.TimeoutExpired):
            return VerificationResult(verifier_type=self.verifier_type, verifier_version=self.verifier_version, status="unavailable", failure_class="verifier_error", details={"reason": "sandbox unavailable"})
        passed = process.returncode == 0
        return VerificationResult(verifier_type=self.verifier_type, verifier_version=self.verifier_version, status="verified" if passed else "conflict", confidence=1.0, evidence=[{"id": str(uuid4()), "title": "Isolated Python test run", "relation": "supporting" if passed else "conflicting"}], details={"passed_tests": 1 if passed else 0, "total_tests": 1, "exit_code": process.returncode, "output": process.stdout[:2000]}, duration_ms=(time.perf_counter() - started) * 1000)


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
