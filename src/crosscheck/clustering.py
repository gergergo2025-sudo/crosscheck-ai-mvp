"""Claim normalization and Claim Cluster extension point.

The orchestrator always calls a clusterer, so grouping behaviour can evolve
(embedding similarity, deterministic lexical fallback) without changing the
query pipeline.  The neutral default records no clusters, which is the honest
result before a similarity source is configured.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from .contracts import ModelAnswer

DEFAULT_SIMILARITY_THRESHOLD = 0.85
DEFAULT_LEXICAL_THRESHOLD = 0.92


def normalize_claim_text(value: str) -> str:
    """Normalize a Claim for matching only; original text stays for display."""

    folded = unicodedata.normalize("NFKC", value or "").casefold()
    folded = re.sub(r"[‘’“”]", "'", folded)
    folded = re.sub(r"[^\w\s]+", " ", folded, flags=re.UNICODE)
    return re.sub(r"\s+", " ", folded).strip()


@dataclass
class ClaimCluster:
    """One group of materially equivalent Claims across Model Answers."""

    id: UUID
    representative_text: str
    representative_claim_id: UUID | None = None
    claim_ids: list[UUID] = field(default_factory=list)
    supporting_models: list[str] = field(default_factory=list)
    oppose_models: list[str] = field(default_factory=list)
    verification_status: str = "pending"
    verification_confidence: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": str(self.id),
            "claim_text": self.representative_text,
            "representative_claim_id": str(self.representative_claim_id)
            if self.representative_claim_id
            else None,
            "claim_ids": [str(claim_id) for claim_id in self.claim_ids],
            "support_models": list(self.supporting_models),
            "oppose_models": list(self.oppose_models),
            "verification_status": self.verification_status,
            "verification_confidence": self.verification_confidence,
        }


@dataclass
class ClusteringOutcome:
    """Clusters plus the recorded method/version/threshold used to build them."""

    clusters: list[ClaimCluster] = field(default_factory=list)
    method: str = "none"
    version: str = "0"
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    degraded: bool = False
    warnings: list[str] = field(default_factory=list)

    def cluster_for_claim(self, claim_id: UUID) -> ClaimCluster | None:
        for cluster in self.clusters:
            if claim_id in cluster.claim_ids:
                return cluster
        return None

    def metadata(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "version": self.version,
            "threshold": self.threshold,
            "degraded": self.degraded,
        }


class ClaimClusterer(Protocol):
    """Provider-neutral clustering port used by the query pipeline."""

    async def cluster(
        self,
        answers: list[ModelAnswer],
        *,
        deadline: float | None = None,
    ) -> ClusteringOutcome:
        """Return clusters as data; a clustering failure must not raise."""


class NullClusterer:
    """Safe default which records no Consensus grouping."""

    method = "none"
    version = "0"

    async def cluster(
        self,
        answers: list[ModelAnswer],
        *,
        deadline: float | None = None,
    ) -> ClusteringOutcome:
        del answers, deadline
        return ClusteringOutcome(method=self.method, version=self.version)
