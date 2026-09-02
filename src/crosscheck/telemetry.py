"""Structured lifecycle telemetry extension point.

Events carry IDs, categories, timings, and sanitized status metadata only.  Raw
Question, Model Answer, feedback bodies, upstream error bodies, and credentials
must never reach this boundary.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any, Protocol


class Telemetry(Protocol):
    """Provider-neutral structured event port used across the pipeline."""

    def emit(self, event: str, **fields: Any) -> None:
        """Record one lifecycle event; emission failures must not raise."""


class NullTelemetry:
    """Safe default which records nothing."""

    def emit(self, event: str, **fields: Any) -> None:
        del event, fields


class StructuredTelemetry:
    """Privacy-safe JSON events and in-process counters for operational seams."""

    _allowed = {
        "request_id", "report_id", "question_type", "question_type_origin", "model_count",
        "usable_model_count", "question_length", "status", "cached", "duration_ms", "model",
        "provider", "retry_count", "latency_ms", "token_count", "reported_cost", "parse_status",
        "repair_attempted", "repair_succeeded", "method", "version", "threshold", "degraded",
        "cluster_count", "constraint_count", "verifier", "score", "outcome", "feedback_id",
    }

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("crosscheck.telemetry")
        self.metrics: Counter[str] = Counter()

    def emit(self, event: str, **fields: Any) -> None:
        try:
            safe = {key: value for key, value in fields.items() if key in self._allowed and isinstance(value, (str, int, float, bool, type(None)))}
            self.metrics[event] += 1
            self.logger.info(json.dumps({"event": str(event)[:100], **safe}, sort_keys=True, separators=(",", ":")))
        except Exception:
            return
