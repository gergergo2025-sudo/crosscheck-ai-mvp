"""Per-Constraint verification extension point.

User Constraints are checked once per submitted requirement rather than per
Claim, so the pipeline keeps a dedicated stage for them.  The neutral default
only aggregates what the models reported, without asserting satisfaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from .contracts import ModelAnswer, QueryRequest


@dataclass
class ConstraintOutcome:
    """Per-answer Constraint Checks plus the aggregate Report summary."""

    per_answer: dict[UUID, list[dict[str, Any]]] = field(default_factory=dict)
    aggregate: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class ConstraintService(Protocol):
    """Provider-neutral Constraint verification port."""

    async def check(
        self,
        request: QueryRequest,
        answers: list[ModelAnswer],
        *,
        deadline: float | None = None,
    ) -> ConstraintOutcome:
        """Return Constraint data; a failure must not raise."""


class ReportedConstraintService:
    """Safe default which surfaces model-reported checks without verifying them."""

    async def check(
        self,
        request: QueryRequest,
        answers: list[ModelAnswer],
        *,
        deadline: float | None = None,
    ) -> ConstraintOutcome:
        del request, deadline
        aggregate: dict[str, Any] = {}
        for answer in answers:
            for key, value in answer.constraints_check.items():
                aggregate.setdefault(key, []).append({"model": answer.model, "result": value})
        return ConstraintOutcome(aggregate=aggregate)
