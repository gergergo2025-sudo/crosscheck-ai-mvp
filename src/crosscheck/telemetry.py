"""Structured lifecycle telemetry extension point.

Events carry IDs, categories, timings, and sanitized status metadata only.  Raw
Question, Model Answer, feedback bodies, upstream error bodies, and credentials
must never reach this boundary.
"""

from __future__ import annotations

from typing import Any, Protocol


class Telemetry(Protocol):
    """Provider-neutral structured event port used across the pipeline."""

    def emit(self, event: str, **fields: Any) -> None:
        """Record one lifecycle event; emission failures must not raise."""


class NullTelemetry:
    """Safe default which records nothing."""

    def emit(self, event: str, **fields: Any) -> None:
        del event, fields
