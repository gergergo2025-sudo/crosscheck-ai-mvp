"""Provider-neutral Verifier ports for the durable tracer."""

from __future__ import annotations

import asyncio
import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import json
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

    def __init__(self, api_key: str | None, *, max_results: int = 5, http_client: httpx.AsyncClient | None = None) -> None:
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

    @staticmethod
    def _recency(publication_date: object) -> tuple[str | None, float]:
        if not isinstance(publication_date, str) or not publication_date.strip():
            return None, 0.5
        value = publication_date.strip()
        try:
            published = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except ValueError:
            return value[:100], 0.0
        age_days = (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).days
        if age_days < -30:
            return value[:100], 0.0
        if age_days <= 366:
            return value[:100], 1.0
        if age_days <= 3 * 366:
            return value[:100], 0.8
        if age_days <= 5 * 366:
            return value[:100], 0.6
        return value[:100], 0.3

    @staticmethod
    def _relation(row: Mapping[str, Any], *, overlap: float, claim_tokens: set[str], result_tokens: set[str]) -> str:
        supplied = str(row.get("relation", "")).casefold()
        if supplied in {"conflict", "conflicting", "contradicting", "contradiction"}:
            return "conflicting"
        if supplied in {"support", "supporting"}:
            return "supporting"
        negations = {"not", "no", "never", "false", "incorrect", "isn", "wasn", "doesn", "cannot"}
        opposite_polarity = bool(claim_tokens & negations) != bool(result_tokens & negations)
        if overlap >= 0.55 and opposite_polarity:
            return "conflicting"
        if overlap >= 0.55:
            return "supporting"
        return "related"

    async def verify(self, claim: Claim, *, question: str, constraints: dict[str, Any] | str | None,
                     deadline: float | None = None) -> VerificationResult:
        del question, constraints
        started = time.perf_counter()
        if not self.api_key:
            return VerificationResult(
                verifier_type=self.verifier_type,
                verifier_version=self.verifier_version,
                status="unavailable",
                confidence=0.0,
                failure_class="configuration_unavailable",
                details={"reason": "fact search is not configured"},
                duration_ms=(time.perf_counter() - started) * 1000,
            )
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
        conflict_scores: list[float] = []
        for rank, row in enumerate(rows, 1):
            if not isinstance(row, Mapping):
                continue
            text_value = f"{row.get('title', '')} {row.get('content', '')}"
            result_tokens = set(re.findall(r"\w+", text_value.casefold()))
            overlap = len(claim_tokens & result_tokens) / max(1, len(claim_tokens))
            url = str(row.get("url", ""))
            domain = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
            authority = self._authority(domain)
            publication_date, recency = self._recency(row.get("published_date") or row.get("publication_date"))
            relation = self._relation(row, overlap=overlap, claim_tokens=claim_tokens, result_tokens=result_tokens)
            evidence_score = (overlap + authority + recency) / 3
            evidence.append({"id": str(uuid4()), "url": row.get("url"), "title": row.get("title"), "snippet": str(row.get("content", ""))[:1000], "domain": domain, "publication_date": publication_date, "rank": rank, "authority": authority, "recency": recency, "relation": relation})
            if relation == "supporting":
                support_scores.append(evidence_score)
            elif relation == "conflicting" and authority >= 0.55:
                conflict_scores.append(evidence_score)
        supporting = [item for item in evidence if item["relation"] == "supporting"]
        independent_domains = {item["domain"] for item in supporting if item["domain"]}
        has_primary = any(item["authority"] >= 0.8 for item in supporting)
        if conflict_scores:
            status = "conflict"
            confidence = max(conflict_scores)
        else:
            status = "verified" if has_primary or len(independent_domains) >= 2 else "unverified"
            confidence = min(1.0, sum(support_scores) / len(support_scores)) if support_scores else 0.0
        return VerificationResult(verifier_type=self.verifier_type, verifier_version=self.verifier_version, status=status, confidence=confidence, evidence=evidence, details={"result_count": len(evidence), "support_count": len(support_scores), "conflict_count": len(conflict_scores)}, duration_ms=(time.perf_counter() - started) * 1000)


@dataclass(frozen=True)
class _BoundedProcessResult:
    returncode: int
    stdout: str
    stderr: str
    output_truncated: bool = False
    timed_out: bool = False


class CodeVerifier:
    verifier_type = "code"
    verifier_version = "docker-python-v4"
    _PYTEST_RESULT_PREFIX = "CROSSCHECK_PYTEST_RESULT="
    _PYTEST_RUNNER = r'''
import json
import os
import sys

os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
import pytest


class CrossCheckResults:
    def __init__(self):
        self.total = 0
        self.outcomes = {}

    def pytest_collection_finish(self, session):
        self.total = len(session.items)

    def pytest_runtest_logreport(self, report):
        if report.failed or report.skipped:
            self.outcomes[report.nodeid] = False
        elif report.when == "call" and report.passed:
            self.outcomes.setdefault(report.nodeid, True)

    @property
    def passed(self):
        return sum(outcome is True for outcome in self.outcomes.values())


sources = json.loads(sys.stdin.read())
paths = []
for index, source in enumerate(sources):
    path = f"/tmp/test_crosscheck_{index}.py"
    with open(path, "w", encoding="utf-8") as test_file:
        test_file.write(source)
    paths.append(path)

results = CrossCheckResults()
exit_code = pytest.main(["-q", "--disable-warnings", "--tb=short", *paths], plugins=[results])
print("\nCROSSCHECK_PYTEST_RESULT=" + json.dumps({"passed": results.passed, "total": results.total}), flush=True)
raise SystemExit(int(exit_code))
'''

    def __init__(self, image: str, *, timeout_seconds: float = 5.0, max_output_bytes: int = 4096) -> None:
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max(256, max_output_bytes)

    @staticmethod
    def _is_explicit_test(source: str) -> bool:
        """Return whether a parseable fence declares an explicit test contract."""

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False

        explicit = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                if any(module.split(".", 1)[0] in {"pytest", "unittest"} for module in modules):
                    explicit = True
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                explicit = True
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                explicit = True
            elif isinstance(node, ast.Assert):
                explicit = True
            elif isinstance(node, ast.Call):
                function_name = ""
                if isinstance(node.func, ast.Attribute):
                    function_name = node.func.attr
                    if function_name == "main" and isinstance(node.func.value, ast.Name) and node.func.value.id == "unittest":
                        explicit = True
                elif isinstance(node.func, ast.Name):
                    function_name = node.func.id
                if function_name.startswith("assert"):
                    explicit = True
                elif (
                    function_name == "raises"
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "pytest"
                ):
                    explicit = True

        return explicit

    @staticmethod
    def _is_inline_test_statement(node: ast.stmt) -> bool:
        """Identify direct assertions that pytest would otherwise run only at collection."""

        if isinstance(node, ast.Assert):
            return True
        calls: list[ast.Call] = []
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            calls.append(node.value)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            calls.extend(
                item.context_expr
                for item in node.items
                if isinstance(item.context_expr, ast.Call)
            )
        for call in calls:
            if isinstance(call.func, ast.Attribute):
                if call.func.attr.startswith("assert"):
                    return True
                if (
                    call.func.attr == "raises"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "pytest"
                ):
                    return True
            elif isinstance(call.func, ast.Name) and call.func.id.startswith("assert"):
                return True
        return False

    @classmethod
    def _prepare_test_block(cls, source: str, block_index: int) -> str:
        """Make direct assertion fences collectable while preserving declared tests."""

        tree = ast.parse(source)
        transformed: list[ast.stmt] = []
        inline_index = 0
        for node in tree.body:
            if cls._is_inline_test_statement(node):
                transformed.append(
                    ast.FunctionDef(
                        name=f"test_crosscheck_inline_{block_index}_{inline_index}",
                        args=ast.arguments(
                            posonlyargs=[],
                            args=[],
                            kwonlyargs=[],
                            kw_defaults=[],
                            defaults=[],
                        ),
                        body=[node],
                        decorator_list=[],
                    )
                )
                inline_index += 1
            else:
                transformed.append(node)
        if inline_index == 0:
            return source
        tree.body = transformed
        ast.fix_missing_locations(tree)
        return ast.unparse(tree) + "\n"

    @classmethod
    def _pytest_counts(cls, stdout: str) -> tuple[int, int, str] | None:
        """Parse and remove the trusted runner's final machine-readable summary."""

        pattern = re.compile(rf"(?m)^{re.escape(cls._PYTEST_RESULT_PREFIX)}([^\r\n]+)\r?$")
        matches = list(pattern.finditer(stdout))
        if not matches:
            return None
        match = matches[-1]
        try:
            payload = json.loads(match.group(1))
            passed_tests = int(payload["passed"])
            total_tests = int(payload["total"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if passed_tests < 0 or total_tests < 0 or passed_tests > total_tests:
            return None
        visible_stdout = (stdout[: match.start()] + stdout[match.end() :]).rstrip("\r\n")
        return passed_tests, total_tests, visible_stdout

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
        fenced_blocks = re.findall(r"```(?:python)?\s*(.*?)```", question, re.I | re.S)
        explicit_tests: list[str] = []
        for block_index, block in enumerate(fenced_blocks):
            if self._is_explicit_test(block):
                explicit_tests.append(self._prepare_test_block(block, block_index))
        if not code_match or not explicit_tests:
            return VerificationResult(verifier_type=self.verifier_type, verifier_version=self.verifier_version, status="unverified", details={"reason": "clearly delimited Python code and explicit tests are required"})
        programs = [code_match.group(1) + "\n\n" + test for test in explicit_tests]
        script = json.dumps(programs)

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
                "--ulimit=fsize=65536:65536", "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
                "--user=65534:65534", self.image, "python", "-I", "-B", "-c", self._PYTEST_RUNNER,
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
        # Docker reserves 125-127 for failures to start the container (including
        # a missing --pull=never image). These are infrastructure availability
        # failures, not evidence that the submitted code conflicts with tests.
        # Do not return daemon stderr because it may contain registry/image or
        # host details.
        daemon_error = process.stderr.casefold()
        docker_start_failure = process.returncode in {125, 126, 127} or any(
            marker in daemon_error
            for marker in (
                "error response from daemon",
                "cannot connect to the docker daemon",
                "unable to find image",
                "no such image",
                "pull access denied",
                "docker daemon socket",
            )
        )
        if docker_start_failure:
            return VerificationResult(
                verifier_type=self.verifier_type,
                verifier_version=self.verifier_version,
                status="unavailable",
                confidence=0.0,
                failure_class="sandbox_unavailable",
                details={"reason": "sandbox image or Docker service unavailable"},
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        runner_result = self._pytest_counts(process.stdout)
        if runner_result is None:
            return VerificationResult(
                verifier_type=self.verifier_type,
                verifier_version=self.verifier_version,
                status="unavailable",
                confidence=0.0,
                failure_class="verifier_error",
                details={"reason": "sandbox test runner did not report results"},
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        passed_tests, total_tests, visible_stdout = runner_result
        passed = process.returncode == 0 and total_tests > 0 and passed_tests == total_tests
        no_tests = total_tests == 0 and process.returncode == 5
        return VerificationResult(
            verifier_type=self.verifier_type,
            verifier_version=self.verifier_version,
            status="verified" if passed else "unverified" if no_tests else "conflict",
            confidence=0.0 if no_tests else 1.0,
            evidence=[{"id": str(uuid4()), "title": "Isolated Python test run", "relation": "supporting" if passed else "context" if no_tests else "conflicting"}],
            details={
                "executed": True,
                "passed_tests": passed_tests,
                "total_tests": total_tests,
                "exit_code": process.returncode,
                "exit_class": "success" if passed else "no_tests" if no_tests else "test_failure",
                "stdout": visible_stdout,
                "stderr": process.stderr,
                "output": visible_stdout,
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
