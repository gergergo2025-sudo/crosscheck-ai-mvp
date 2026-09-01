"""Verified Consensus and explicit Disagreement extension point.

Consensus requires independent verification, never model agreement alone, so the
pipeline delegates the decision to this boundary.  The neutral default reports
nothing rather than implying agreement.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from .clustering import ClusteringOutcome
from .contracts import ModelAnswer, VerificationResult


def build_consensus_and_disagreements(
    answers: list[ModelAnswer],
    *,
    clustering: ClusteringOutcome,
    verification_by_claim: dict[UUID, list[VerificationResult]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(consensus, disagreements)`` as serializable Report sections."""

    del answers, clustering, verification_by_claim
    return [], []
