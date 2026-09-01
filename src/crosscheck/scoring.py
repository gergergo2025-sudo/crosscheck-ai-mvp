"""Scoring and recommendation extension point.

The pipeline always asks a scorer for per-answer component breakdowns and a
recommendation decision.  The neutral default scores nothing and recommends
nothing, which keeps the tracer honest until evidence-backed components exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from .clustering import ClusteringOutcome
from .contracts import ModelAnswer, VerificationResult

# PRD weights.  Effective weights are renormalized over applicable components.
DEFAULT_WEIGHTS: dict[str, float] = {
    "fact_verification": 0.30,
    "source_authority": 0.15,
    "execution": 0.20,
    "constraint_satisfaction": 0.20,
    "consensus": 0.15,
}
RECOMMENDATION_THRESHOLD = 0.60
INSUFFICIENT_CONFIDENCE_MESSAGE = (
    "No answer reached the confidence threshold. Review the evidence and "
    "disagreements below before relying on any single answer."
)
NO_SCORING_MESSAGE = (
    "Verification and scoring are not yet sufficient for an automated recommendation."
)


@dataclass
class ScoringOutcome:
    """Per-answer scores plus the recommendation decision and its reasons."""

    scores: dict[UUID, float] = field(default_factory=dict)
    components: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    recommended_answer_id: UUID | None = None
    recommendation_message: str = NO_SCORING_MESSAGE
    warnings: list[str] = field(default_factory=list)


class Scorer(Protocol):
    """Provider-neutral scoring port used by the query pipeline."""

    def score(
        self,
        answers: list[ModelAnswer],
        *,
        clustering: ClusteringOutcome,
        verification_by_claim: dict[UUID, list[VerificationResult]],
        constraint_results: dict[UUID, list[dict[str, Any]]],
        usable_provider_count: int,
    ) -> ScoringOutcome:
        """Return scoring data; scoring failures must not raise."""


class NeutralScorer:
    """Safe default which scores zero and makes no recommendation."""

    def score(
        self,
        answers: list[ModelAnswer],
        *,
        clustering: ClusteringOutcome,
        verification_by_claim: dict[UUID, list[VerificationResult]],
        constraint_results: dict[UUID, list[dict[str, Any]]],
        usable_provider_count: int,
    ) -> ScoringOutcome:
        del clustering, verification_by_claim, constraint_results, usable_provider_count
        return ScoringOutcome(
            scores={answer.id: 0.0 for answer in answers},
            components={answer.id: {} for answer in answers},
        )
