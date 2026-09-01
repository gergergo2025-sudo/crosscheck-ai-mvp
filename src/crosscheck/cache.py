"""Exact Report cache extension point.

The cache is an optimization, never a source of truth: a lookup miss, a stale
reference, or a backend outage must leave the query working.  The neutral
default never stores anything.
"""

from __future__ import annotations

import hashlib
import json
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


__all__ = [
    "CACHE_KEY_VERSION",
    "NullReportCache",
    "ReportCache",
    "build_cache_key",
]
