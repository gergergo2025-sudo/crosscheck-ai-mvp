"""The provider-neutral Unified Prompt used by every Adapter."""

from __future__ import annotations

import json
from typing import Any


PROMPT_VERSION = "unified-v1"


def build_unified_prompt(
    question: str,
    constraints: dict[str, Any] | str | None,
    question_type: str,
    expected_output_format: str | None,
    *,
    version: str = PROMPT_VERSION,
) -> str:
    """Build equivalent substantive instructions for all providers.

    Credentials, transport headers, and provider-specific options are deliberately
    absent from this function and therefore cannot cross the Adapter boundary.
    """

    constraints_text = (
        json.dumps(constraints, ensure_ascii=False, sort_keys=True)
        if isinstance(constraints, dict)
        else (constraints or "")
    )
    output_format = expected_output_format or "plain"
    return f"""CrossCheck Unified Prompt {version}

Answer the user's single-turn question accurately and concisely.

Question:
{question}

Constraints (empty means none):
{constraints_text}

Selected question type: {question_type}
Expected output format: {output_format}

Return one strict JSON object and no surrounding prose.  Use exactly these
top-level fields: answer (string), reasoning (concise rationale string), claims
(array), and constraints_check (object).  Each claim must have claim (string),
type (fact, code, math, logic, opinion, or recommendation), confidence (number
from 0 to 1), and may include source and assumptions.  Do not invent sources.
The reasoning is a concise explanation suitable for display, not private
chain-of-thought.  Check every supplied constraint separately.
"""
