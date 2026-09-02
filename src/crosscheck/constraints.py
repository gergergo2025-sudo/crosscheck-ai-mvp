"""Per-Constraint verification extension point.

User Constraints are checked once per submitted requirement rather than per
Claim, so the pipeline keeps a dedicated stage for them.  The neutral default
only aggregates what the models reported, without asserting satisfaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
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


class IndependentConstraintService:
    """Rule-based, provenance-preserving checks for explicit MVP constraints."""

    version = "constraint-v2"

    @staticmethod
    def _submitted(value: dict[str, Any] | str | None) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        budget = re.search(r"(?:budget|预算)\D{0,12}([\d,.]+)", value, re.I)
        return {"budget": float(budget.group(1).replace(",", ""))} if budget else {"requirement": value.strip()}

    @staticmethod
    def _number(value: Any) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        match = re.search(r"[\d,.]+", str(value))
        return float(match.group().replace(",", "")) if match else None

    async def check(self, request: QueryRequest, answers: list[ModelAnswer], *, deadline: float | None = None) -> ConstraintOutcome:
        del deadline
        submitted = self._submitted(request.constraints)
        per_answer: dict[UUID, list[dict[str, Any]]] = {}
        aggregate: dict[str, Any] = {}
        for answer in answers:
            checks: list[dict[str, Any]] = []
            normalized_answer = answer.answer.casefold()
            for key, expected in submitted.items():
                name = str(key).strip().casefold()
                comparator = "contains"
                observed: Any = None
                status = "indeterminate"
                reason = "the answer did not expose a comparable value"
                if name in {"budget", "price", "max_price"}:
                    expected_number = self._number(expected)
                    price = re.search(r"(?:price|cost|价格|售价)?\s*[:：]?\s*[¥￥$]?\s*([\d,.]+)\s*(?:元|rmb|usd|美元)?", answer.answer, re.I)
                    observed = self._number(price.group(1)) if price else None
                    comparator = "lte"
                    if expected_number is not None and observed is not None:
                        status = "satisfied" if observed <= expected_number else "violated"
                        reason = "observed value is within the maximum" if status == "satisfied" else "observed value exceeds the maximum"
                    expected = expected_number
                else:
                    values = expected if isinstance(expected, list) else [expected]
                    wanted = [str(item).casefold() for item in values]
                    matches = [item for item in wanted if item in normalized_answer]
                    observed = matches
                    if name in {"exclude_brands", "exclude", "excluded"}:
                        comparator = "excludes"
                        status = "violated" if matches else "satisfied"
                        reason = "an excluded value appears in the answer" if matches else "no excluded value appears in the answer"
                    else:
                        status = "satisfied" if len(matches) == len(wanted) else "indeterminate"
                        reason = "the answer contains the requested value" if status == "satisfied" else "the requested value was not established"
                checks.append({"constraint": name, "expected": expected, "observed": observed, "comparator": comparator, "status": status, "reason": reason, "provenance": "submitted constraint + model answer"})
            per_answer[answer.id] = checks
        for key in submitted:
            rows = [item for checks in per_answer.values() for item in checks if item["constraint"] == str(key).casefold()]
            statuses = [item["status"] for item in rows]
            aggregate[str(key)] = {
                "status": "satisfied" if statuses and all(value == "satisfied" for value in statuses) else ("violated" if "violated" in statuses else "indeterminate"),
                "reason": "aggregated across model answers",
                "checks": rows,
            }
        return ConstraintOutcome(per_answer=per_answer, aggregate=aggregate)
