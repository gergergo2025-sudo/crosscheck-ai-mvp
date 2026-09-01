"""Strict Structured Answer parsing with a safe degraded fallback."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .contracts import StructuredAnswer


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_MAX_CANDIDATES = 2


@dataclass(frozen=True)
class ParsedAnswer:
    structured: StructuredAnswer | None
    parse_status: str
    diagnostics: list[str]
    raw_text: str
    repair_attempted: bool = False
    repair_succeeded: bool = False

    @property
    def parse_success(self) -> bool:
        return self.structured is not None


def _balanced_json_candidates(raw_text: str) -> list[dict[str, Any]]:
    """Find JSON objects without attempting to interpret prose as JSON.

    ``JSONDecoder.raw_decode`` handles braces inside quoted strings correctly.  At
    most two candidates are retained so a maliciously large provider response does
    not create unbounded parser work.
    """

    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    index = 0
    while index < len(raw_text):
        char = raw_text[index]
        if char != "{":
            index += 1
            continue
        try:
            value, consumed = decoder.raw_decode(raw_text[index:])
        except (ValueError, TypeError):
            index += 1
            continue
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            candidates.append(value)
            if len(candidates) >= _MAX_CANDIDATES:
                break
            # Skip the complete object so nested claim dictionaries are not
            # mistaken for an additional top-level candidate.
            index += consumed
            continue
        index += 1
    return candidates


def _candidate_objects(raw_text: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw_text)
    except (ValueError, TypeError):
        value = None
    if isinstance(value, dict):
        return [value]

    fenced = _FENCED_JSON_RE.findall(raw_text)
    if len(fenced) == 1:
        try:
            value = json.loads(fenced[0])
        except (ValueError, TypeError):
            value = None
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            return [value]
        # A single malformed fence is an explicit structured-output attempt.  Do
        # not accidentally recover a nested fragment from it as if it were an
        # unambiguous answer; the orchestrator can issue the bounded repair call.
        return []
    if len(fenced) > 1:
        return []
    return _balanced_json_candidates(raw_text)


def parse_structured_answer(raw_text: str, *, max_chars: int = 120_000) -> ParsedAnswer:
    bounded = (raw_text or "")[: max(1, max_chars)]
    candidates = _candidate_objects(bounded)
    if len(candidates) != 1:
        reason = "structured JSON object not found" if not candidates else "ambiguous structured JSON"
        return ParsedAnswer(None, "degraded", [reason], bounded)
    try:
        answer = StructuredAnswer.model_validate(candidates[0])
    except ValidationError:
        # Do not expose provider content or Pydantic internals in the public report.
        return ParsedAnswer(None, "degraded", ["structured answer failed schema validation"], bounded)
    return ParsedAnswer(answer, "parsed", [], bounded)


async def parse_with_repair(
    raw_text: str,
    repair: Callable[[str], str | Awaitable[str]],
    *,
    max_chars: int = 120_000,
) -> ParsedAnswer:
    """Parse a response and perform at most one bounded repair attempt.

    The callback receives the bounded original response and is intentionally kept
    provider-neutral.  Transport retries belong to the Adapter policy; this
    helper only handles a single malformed structured response.  If repair fails,
    the returned ``raw_text`` remains the original response so audit/storage and
    the user-facing degraded answer cannot be replaced by an untrusted repair
    payload.
    """

    initial = parse_structured_answer(raw_text, max_chars=max_chars)
    if initial.parse_success:
        return initial
    try:
        repaired_value = repair(initial.raw_text)
        if hasattr(repaired_value, "__await__"):
            repaired_value = await repaired_value  # type: ignore[assignment]
    except Exception:
        return ParsedAnswer(
            None,
            "degraded",
            [*initial.diagnostics, "repair attempt failed"],
            initial.raw_text,
            repair_attempted=True,
            repair_succeeded=False,
        )
    repaired = parse_structured_answer(str(repaired_value or ""), max_chars=max_chars)
    if repaired.parse_success:
        return ParsedAnswer(
            repaired.structured,
            "parsed",
            ["structured response repaired"],
            initial.raw_text,
            repair_attempted=True,
            repair_succeeded=True,
        )
    return ParsedAnswer(
        None,
        "degraded",
        [*initial.diagnostics, "repair response failed schema validation"],
        initial.raw_text,
        repair_attempted=True,
        repair_succeeded=False,
    )
