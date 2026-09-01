"""Deterministic Question classification with an explicit precedence order."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal


ResolvedQuestionType = Literal["fact", "code", "constraint"]
ClassificationOrigin = Literal[
    "explicit",
    "deterministic_code",
    "deterministic_constraints",
    "classifier",
    "fallback",
]


@dataclass(frozen=True)
class ClassificationResult:
    question_type: ResolvedQuestionType
    origin: ClassificationOrigin


Classifier = Callable[[str, dict[str, Any] | str | None], str | None | Awaitable[str | None]]


_CODE_RE = re.compile(
    r"(?:```(?:python|py)?\b|\bpython\b|\b(?:code|coding|function|algorithm|implementation|implement)\b|"
    r"(?:实现|编写|代码|算法|函数|排序|程序))",
    re.IGNORECASE,
)
_CONSTRAINT_RE = re.compile(
    r"(?:budget|price|cost|under|less than|within|weight|duration|deadline|prefer|exclude|must|"
    r"预算|价格|成本|不超过|低于|重量|时长|截止|偏好|排除|必须|用于)",
    re.IGNORECASE,
)
_FACT_RE = re.compile(
    r"(?:^|\s)(?:who|what|when|where|which|how many|how much|是谁|什么|何时|哪里|哪位|多少)",
    re.IGNORECASE,
)


class BoundedQuestionClassifier:
    """A local, bounded classifier used only after deterministic signals.

    It intentionally returns ``None`` for ambiguous prompts.  The orchestrator
    then records a conservative ``fact`` fallback instead of making an uncertain
    product decision.
    """

    def __call__(self, question: str, constraints: dict[str, Any] | str | None) -> str | None:
        if isinstance(constraints, str) and _CONSTRAINT_RE.search(constraints):
            return "constraint"
        if _FACT_RE.search(question):
            return "fact"
        if _CONSTRAINT_RE.search(question):
            return "constraint"
        return None


def has_deterministic_code_signal(question: str) -> bool:
    return bool(_CODE_RE.search(question))


def has_structured_constraints(constraints: dict[str, Any] | str | None) -> bool:
    return isinstance(constraints, dict) and bool(constraints)


async def resolve_classification(
    question: str,
    constraints: dict[str, Any] | str | None,
    explicit_type: str = "auto",
    classifier: Classifier | None = None,
) -> ClassificationResult:
    """Resolve type using explicit > code > structured constraints > classifier > fact."""

    if explicit_type != "auto":
        return ClassificationResult(explicit_type, "explicit")  # type: ignore[arg-type]
    if has_deterministic_code_signal(question):
        return ClassificationResult("code", "deterministic_code")
    if has_structured_constraints(constraints):
        return ClassificationResult("constraint", "deterministic_constraints")

    classifier_fn = classifier or BoundedQuestionClassifier()
    try:
        classify_method = getattr(classifier_fn, "classify", None)
        selected = (
            classify_method(question, constraints)
            if callable(classify_method)
            else classifier_fn(question, constraints)
        )
        if hasattr(selected, "__await__"):
            selected = await selected  # type: ignore[assignment]
    except Exception:
        selected = None
    if selected in {"fact", "code", "constraint"}:
        return ClassificationResult(selected, "classifier")  # type: ignore[arg-type]
    return ClassificationResult("fact", "fallback")
