"""Exact Report cache extension point.

The cache is an optimization, never a source of truth: a lookup miss, a stale
reference, or a backend outage must leave the query working.  The neutral
default never stores anything.
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4
from typing import Any, Protocol

from .contracts import QueryRequest, ReportResponse

CACHE_KEY_VERSION = "cachekey-v1"


def _canonical_constraints(value: dict[str, Any] | str | None) -> Any:
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def build_cache_key(
    request: QueryRequest,
    *,
    models: list[str],
    question_type: str,
    versions: dict[str, Any],
) -> str:
    """Return a secret-free digest of every result-affecting input and version."""

    payload = {
        "key_version": CACHE_KEY_VERSION,
        "question": " ".join((request.question or "").split()),
        "constraints": _canonical_constraints(request.constraints),
        "question_type": question_type,
        "expected_output_format": request.expected_output_format,
        "models": list(models),
        "versions": dict(sorted(versions.items())),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ReportCache(Protocol):
    """Provider-neutral cache port used by the query pipeline."""

    async def get(self, key: str) -> ReportResponse | None:
        """Return a cached Report or ``None``; never raise on backend failure."""

    async def set(self, key: str, report: ReportResponse) -> None:
        """Store a committed Report; never raise on backend failure."""

    def warnings(self) -> list[str]:
        """Return sanitized degradation warnings observed during this request."""


class NullReportCache:
    """Safe default used when no cache backend is configured."""

    async def get(self, key: str) -> ReportResponse | None:
        del key
        return None

    async def set(self, key: str, report: ReportResponse) -> None:
        del key, report

    def warnings(self) -> list[str]:
        return []

    async def acquire_lock(self, key: str) -> str | None:
        del key
        return "null"

    async def release_lock(self, key: str, token: str) -> None:
        del key, token


class RedisReportCache:
    """Redis optimization storing only validated committed Report snapshots."""

    def __init__(self, url: str, *, store: Any, ttl_seconds: int = 86_400, lock_seconds: int = 20) -> None:
        from redis.asyncio import Redis
        self.client = Redis.from_url(url, decode_responses=True, socket_connect_timeout=.25, socket_timeout=.5)
        self.store = store
        self.ttl_seconds = ttl_seconds
        self.lock_seconds = lock_seconds
        self._warnings: list[str] = []

    def _warn(self) -> None:
        message = "Redis cache is unavailable; the query continued without caching"
        if message not in self._warnings:
            self._warnings.append(message)

    async def get(self, key: str) -> ReportResponse | None:
        try:
            raw = await self.client.get(f"crosscheck:report:{key}")
            if not raw:
                return None
            report = ReportResponse.model_validate_json(raw)
            if not await self.store.report_exists(report.report_id):
                await self.client.delete(f"crosscheck:report:{key}")
                return None
            return report
        except Exception:
            self._warn()
            return None

    async def set(self, key: str, report: ReportResponse) -> None:
        try:
            if await self.store.report_exists(report.report_id):
                await self.client.set(f"crosscheck:report:{key}", report.model_dump_json(), ex=self.ttl_seconds)
        except Exception:
            self._warn()

    async def acquire_lock(self, key: str) -> str | None:
        token = str(uuid4())
        try:
            acquired = await self.client.set(f"crosscheck:lock:{key}", token, nx=True, ex=self.lock_seconds)
            return token if acquired else None
        except Exception:
            self._warn()
            return "degraded"

    async def release_lock(self, key: str, token: str) -> None:
        if token in {"degraded", "null"}:
            return
        try:
            lock_key = f"crosscheck:lock:{key}"
            if await self.client.get(lock_key) == token:
                await self.client.delete(lock_key)
        except Exception:
            self._warn()

    def warnings(self) -> list[str]:
        return list(self._warnings)


__all__ = [
    "CACHE_KEY_VERSION",
    "NullReportCache",
    "RedisReportCache",
    "ReportCache",
    "build_cache_key",
]
