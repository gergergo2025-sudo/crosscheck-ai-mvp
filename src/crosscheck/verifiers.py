"""Provider-neutral Verifier ports for the durable tracer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
import re
import selectors
import subprocess
import time
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit
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
    verifier_version = "tavily-v2"

    def __init__(self, api_key: str, *, max_results: int = 5, http_client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self.max_results = max(5, min(10, max_results))
        self.http_client = http_client

    @staticmethod
    def _is_host(hostname: str, expected: str) -> bool:
        """Match an authority host itself or a real subdomain, never a substring."""

        return hostname == expected or hostname.endswith(f".{expected}")

    @classmethod
    def _authority(cls, hostname: str) -> float:
        trusted_publishers = ("reuters.com", "apnews.com", "nature.com", "science.org", "bbc.com", "bbc.co.uk")
        if hostname.endswith((".gov", ".edu")) or any(cls._is_host(hostname, publisher) for publisher in trusted_publishers):
            return 0.9
        # Wikipedia is useful corroboration but is deliberately not elevated to
        # primary/high-authority status.
        return 0.55

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
            domain = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
            authority = self._authority(domain)
            evidence.append({"id": str(uuid4()), "url": row.get("url"), "title": row.get("title"), "snippet": str(row.get("content", ""))[:1000], "domain": domain, "rank": rank, "authority": authority, "relation": "supporting" if relation >= .55 else "context"})
            if relation >= .55:
                support_scores.append((relation + authority) / 2)
        supporting = [item for item in evidence if item["relation"] == "supporting"]
        independent_domains = {item["domain"] for item in supporting if item["domain"]}
        has_primary = any(item["authority"] >= 0.8 for item in supporting)
        status = "verified" if has_primary or len(independent_domains) >= 2 else "unverified"
        confidence = min(1.0, sum(support_scores) / len(support_scores)) if support_scores else 0.0
        return VerificationResult(verifier_type=self.verifier_type, verifier_version=self.verifier_version, status=status, confidence=confidence, evidence=evidence, details={"result_count": len(evidence), "support_count": len(support_scores)}, duration_ms=(time.perf_counter() - started) * 1000)


@dataclass(frozen=True)
class _BoundedProcessResult:
    returncode: int
    stdout: str
    stderr: str
    output_truncated: bool = False
    timed_out: bool = False


class CodeVerifier:
    verifier_type = "code"
    verifier_version = "docker-python-v2"

    def __init__(self, image: str, *, timeout_seconds: float = 5.0, max_output_bytes: int = 4096) -> None:
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max(256, max_output_bytes)

    @staticmethod
    def _run_bounded(
        command: list[str],
        script: str,
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> _BoundedProcessResult:
        """Stream a child process and kill it before output can grow unbounded."""

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        try:
            try:
                process.stdin.write(script.encode("utf-8"))
                process.stdin.close()
            except BrokenPipeError:
                pass

            streams = {process.stdout: bytearray(), process.stderr: bytearray()}
            with selectors.DefaultSelector() as selector:
                for stream in streams:
                    selector.register(stream, selectors.EVENT_READ)
                deadline = time.monotonic() + timeout_seconds
                output_truncated = False
                timed_out = False
                while selector.get_map():
                    remaining_time = deadline - time.monotonic()
                    if remaining_time <= 0:
                        timed_out = True
                        break
                    events = selector.select(min(0.05, remaining_time))
                    for key, _ in events:
                        remaining_output = max_output_bytes - sum(len(value) for value in streams.values())
                        chunk = os.read(key.fd, min(4096, remaining_output + 1))
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        destination = streams[key.fileobj]
                        destination.extend(chunk[:remaining_output])
                        if len(chunk) > remaining_output:
                            output_truncated = True
                            break
                    if output_truncated:
                        break
            if output_truncated or timed_out:
                process.kill()
            try:
                returncode = process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait(timeout=1.0)
            return _BoundedProcessResult(
                returncode=returncode,
                stdout=bytes(streams[process.stdout]).decode("utf-8", errors="replace"),
                stderr=bytes(streams[process.stderr]).decode("utf-8", errors="replace"),
                output_truncated=output_truncated,
                timed_out=timed_out,
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1.0)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    @staticmethod
    def _remove_container(container_name: str) -> None:
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    async def verify(self, claim: Claim, *, question: str, constraints: dict[str, Any] | str | None,
                     deadline: float | None = None) -> VerificationResult:
        del constraints, deadline
        code_match = re.search(r"```(?:python)?\s*(.*?)```", claim.claim, re.I | re.S)
        test_blocks = re.findall(r"```(?:python)?\s*(.*?)```", question, re.I | re.S)
        if not code_match or not test_blocks:
            return VerificationResult(verifier_type=self.verifier_type, verifier_version=self.verifier_version, status="unverified", details={"reason": "clearly delimited Python code and explicit tests are required"})
        script = code_match.group(1) + "\n\n" + test_blocks[-1]

        container_name = f"crosscheck-{uuid4().hex}"

        def run() -> _BoundedProcessResult:
            # Stream the bounded program over stdin. When the backend uses the
            # host Docker socket, host-path bind mounts would incorrectly refer
            # to the daemon host rather than this container's temporary files.
            command = [
                "docker", "run", "--rm", "-i", "--name", container_name,
                "--pull=never", "--network=none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--memory=128m", "--memory-swap=128m",
                "--cpus=.5", "--pids-limit=64", "--ulimit=nofile=64:64",
                f"--ulimit=cpu={max(1, int(self.timeout_seconds) + 1)}:{max(1, int(self.timeout_seconds) + 1)}",
                "--ulimit=fsize=1024:1024", "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
                "--user=65534:65534", self.image, "python", "-I", "-B", "-",
            ]
            return self._run_bounded(
                command,
                script,
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
        started = time.perf_counter()
        try:
            process = await asyncio.to_thread(run)
        except (OSError, subprocess.TimeoutExpired):
            await asyncio.to_thread(self._remove_container, container_name)
            return VerificationResult(verifier_type=self.verifier_type, verifier_version=self.verifier_version, status="unavailable", failure_class="verifier_error", details={"reason": "sandbox unavailable"})
        if process.timed_out or process.output_truncated:
            await asyncio.to_thread(self._remove_container, container_name)
            exit_class = "timeout" if process.timed_out else "output_limit"
            return VerificationResult(
                verifier_type=self.verifier_type,
                verifier_version=self.verifier_version,
                status="unverified",
                confidence=0.0,
                evidence=[{"id": str(uuid4()), "title": "Isolated Python test run", "relation": "context"}],
                details={
                    "executed": True,
                    "passed_tests": 0,
                    "total_tests": 0,
                    "exit_code": process.returncode,
                    "exit_class": exit_class,
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                    "output": process.stdout,
                    "output_truncated": process.output_truncated,
                },
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        passed = process.returncode == 0
        return VerificationResult(
            verifier_type=self.verifier_type,
            verifier_version=self.verifier_version,
            status="verified" if passed else "conflict",
            confidence=1.0,
            evidence=[{"id": str(uuid4()), "title": "Isolated Python test run", "relation": "supporting" if passed else "conflicting"}],
            details={
                "executed": True,
                "passed_tests": 1 if passed else 0,
                "total_tests": 1,
                "exit_code": process.returncode,
                "exit_class": "success" if passed else "test_failure",
                "stdout": process.stdout,
                "stderr": process.stderr,
                "output": process.stdout,
                "output_truncated": False,
            },
            duration_ms=(time.perf_counter() - started) * 1000,
        )


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
