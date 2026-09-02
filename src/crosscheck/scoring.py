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


class EvidenceScorer:
    """Five-component PRD scorer with applicability normalization and caps."""

    version = "scoring-v2:0.30,0.15,0.20,0.20,0.15:threshold-0.60"

    @staticmethod
    def _component(numerator: float, denominator: float, weight: float) -> dict[str, Any]:
        applicable = denominator > 0
        return {"numerator": numerator, "denominator": denominator, "score": numerator / denominator if applicable else 0.0,
                "weight": weight, "effective_weight": 0.0, "applicable": applicable}

    def score(self, answers: list[ModelAnswer], *, clustering: ClusteringOutcome,
              verification_by_claim: dict[UUID, list[VerificationResult]],
              constraint_results: dict[UUID, list[dict[str, Any]]], usable_provider_count: int) -> ScoringOutcome:
        del usable_provider_count
        scores: dict[UUID, float] = {}
        breakdowns: dict[UUID, dict[str, Any]] = {}
        verified_consensus_claims = {
            claim_id for cluster in clustering.clusters if len(set(cluster.supporting_models)) >= 2
            for claim_id in cluster.claim_ids
            if any(result.status == "verified" for result in verification_by_claim.get(cluster.representative_claim_id, []))
        }
        for answer in answers:
            fact_claims = [claim for claim in answer.claims if claim.type == "fact"]
            fact_results = [result for claim in fact_claims for result in verification_by_claim.get(claim.id, [])]
            verified_facts = sum(1 for claim in fact_claims if any(result.status == "verified" for result in verification_by_claim.get(claim.id, [])))
            authorities = [float(item.get("authority", 0)) for result in fact_results if result.status == "verified" for item in result.evidence if isinstance(item.get("authority"), (int, float))]
            code_results = [result for claim in answer.claims if claim.type == "code" for result in verification_by_claim.get(claim.id, [])]
            passed = sum(float(result.details.get("passed_tests", 0)) for result in code_results)
            total_tests = sum(float(result.details.get("total_tests", 0)) for result in code_results)
            checks = constraint_results.get(answer.id, [])
            satisfied = sum(1 for check in checks if check.get("status") == "satisfied")
            consensus_total = len(answer.claims)
            consensus_passed = sum(1 for claim in answer.claims if claim.id in verified_consensus_claims)
            components = {
                "fact_verification": self._component(verified_facts, len(fact_claims), DEFAULT_WEIGHTS["fact_verification"]),
                "source_authority": self._component(sum(authorities), len(authorities), DEFAULT_WEIGHTS["source_authority"]),
                "execution": self._component(passed, total_tests, DEFAULT_WEIGHTS["execution"]),
                "constraint_satisfaction": self._component(satisfied, len(checks), DEFAULT_WEIGHTS["constraint_satisfaction"]),
                "consensus": self._component(consensus_passed, consensus_total, DEFAULT_WEIGHTS["consensus"]),
            }
            applicable_weight = sum(item["weight"] for item in components.values() if item["applicable"])
            raw_score = 0.0
            for item in components.values():
                if item["applicable"] and applicable_weight:
                    item["effective_weight"] = item["weight"] / applicable_weight
                    raw_score += item["score"] * item["effective_weight"]
            if answer.parse_status != "parsed":
                raw_score = 0.0
            if any(result.status == "conflict" for claim in answer.claims for result in verification_by_claim.get(claim.id, [])):
                raw_score = min(raw_score, RECOMMENDATION_THRESHOLD - .01)
                components["assurance_cap"] = {"cap": RECOMMENDATION_THRESHOLD - .01, "reason": "independent verification conflict"}
            scores[answer.id] = max(0.0, min(1.0, raw_score))
            breakdowns[answer.id] = components
        eligible = [answer for answer in answers if answer.parse_status == "parsed" and scores[answer.id] >= RECOMMENDATION_THRESHOLD]
        eligible.sort(key=lambda answer: (-scores[answer.id], answers.index(answer)))
        warnings: list[str] = []
        recommended = eligible[0].id if eligible else None
        if len(eligible) > 1 and abs(scores[eligible[0].id] - scores[eligible[1].id]) < 1e-12:
            warnings.append("top answers are tied; configured model order selected the displayed answer")
        message = f"Recommended answer reached the {RECOMMENDATION_THRESHOLD:.2f} evidence threshold." if recommended else INSUFFICIENT_CONFIDENCE_MESSAGE
        return ScoringOutcome(scores=scores, components=breakdowns, recommended_answer_id=recommended, recommendation_message=message, warnings=warnings)
