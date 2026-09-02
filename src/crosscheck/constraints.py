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

    version = "constraint-v3"

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

    @staticmethod
    def _currency(value: Any) -> str | None:
        text = str(value).upper()
        if "USD" in text or "US$" in text or "$" in text:
            return "USD"
        if any(token in text for token in ("CNY", "RMB", "¥", "￥", "元")):
            return "CNY"
        if "EUR" in text or "€" in text:
            return "EUR"
        if "GBP" in text or "£" in text:
            return "GBP"
        return None

    @classmethod
    def _money(cls, value: Any) -> tuple[float | None, str | None]:
        if isinstance(value, dict):
            amount = cls._number(value.get("value", value.get("amount")))
            currency = cls._currency(value.get("currency", ""))
            return amount, currency
        return cls._number(value), cls._currency(value)

    @classmethod
    def _observed_money(cls, answer: str) -> tuple[float | None, str | None]:
        price = re.search(
            r"(?:price|cost|价格|售价)\s*[:：]?\s*"
            r"(?P<prefix>US\$|USD|CNY|RMB|[$¥￥€£])?\s*"
            r"(?P<amount>[\d,.]+)\s*"
            r"(?P<suffix>USD|CNY|RMB|EUR|GBP|美元|元)?",
            answer,
            re.I,
        )
        if not price:
            price = re.search(
                r"(?P<prefix>US\$|USD|CNY|RMB|[$¥￥€£])\s*"
                r"(?P<amount>[\d,.]+)\s*"
                r"(?P<suffix>USD|CNY|RMB|EUR|GBP|美元|元)?",
                answer,
                re.I,
            )
        if not price:
            return None, None
        currency_text = f"{price.group('prefix') or ''} {price.group('suffix') or ''}"
        return cls._number(price.group("amount")), cls._currency(currency_text)

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
                    expected_number, expected_currency = self._money(expected)
                    observed_number, observed_currency = self._observed_money(answer.answer)
                    observed = observed_number
                    comparator = "lte"
                    if expected_currency:
                        expected = {"value": expected_number, "currency": expected_currency}
                        observed = {"value": observed_number, "currency": observed_currency} if observed_number is not None else None
                    else:
                        expected = expected_number
                    if expected_currency and expected_currency != observed_currency:
                        status = "indeterminate"
                        reason = "expected and observed currency values are not safely comparable"
                    elif expected_number is not None and observed_number is not None:
                        status = "satisfied" if observed_number <= expected_number else "violated"
                        reason = "observed value is within the maximum" if status == "satisfied" else "observed value exceeds the maximum"
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
