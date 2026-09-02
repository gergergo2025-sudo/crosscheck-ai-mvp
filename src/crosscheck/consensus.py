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

    answer_by_claim = {claim.id: answer for answer in answers for claim in answer.claims if claim.id}
    consensus: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    for cluster in clustering.clusters:
        representative_results = verification_by_claim.get(cluster.representative_claim_id, [])
        result = representative_results[0] if representative_results else None
        distinct_providers = []
        for claim_id in cluster.claim_ids:
            answer = answer_by_claim.get(claim_id)
            if answer and answer.provider not in distinct_providers:
                distinct_providers.append(answer.provider)
        answer_ids = [str(answer_by_claim[claim_id].id) for claim_id in cluster.claim_ids if claim_id in answer_by_claim]
        evidence_ids = [str(item.get("id")) for item in (result.evidence if result else []) if item.get("id")]
        common = {"cluster_id": str(cluster.id), "claim_text": cluster.representative_text,
                  "claim_ids": [str(value) for value in cluster.claim_ids], "answer_ids": list(dict.fromkeys(answer_ids)),
                  "support_models": cluster.supporting_models, "support_providers": distinct_providers,
                  "verification_status": result.status if result else "unavailable", "evidence_ids": evidence_ids}
        if len(distinct_providers) >= 2 and result and result.status == "verified":
            consensus.append(common)
        else:
            if len(cluster.claim_ids) == 1:
                reason = "singleton claim"
            elif len(distinct_providers) < 2:
                reason = "support is not from two distinct providers"
            elif not result:
                reason = "representative verification is unavailable"
            else:
                reason = f"representative verification is {result.status}"
            disagreements.append({**common, "reason": reason})
    if not clustering.clusters:
        for answer in answers:
            if answer.parse_status == "parsed":
                disagreements.append({"answer_ids": [str(answer.id)], "claim_text": answer.answer[:500], "reason": "answer-level alternative without clustered claims"})
    return consensus, disagreements
