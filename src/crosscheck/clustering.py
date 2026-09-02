"""Claim normalization and Claim Cluster extension point.

The orchestrator always calls a clusterer, so grouping behaviour can evolve
(embedding similarity, deterministic lexical fallback) without changing the
query pipeline.  The neutral default records no clusters, which is the honest
result before a similarity source is configured.
"""

from __future__ import annotations

import re
import unicodedata
import math
from difflib import SequenceMatcher
import httpx
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


class EmbeddingService(Protocol):
    version: str

    async def embed(self, texts: list[str], *, deadline: float | None = None) -> list[list[float]]:
        """Return one finite vector per input text."""


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    ln = math.sqrt(sum(a * a for a in left))
    rn = math.sqrt(sum(b * b for b in right))
    return dot / (ln * rn) if ln and rn else 0.0


def _lexical_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    left_tokens, right_tokens = set(left.split()), set(right.split())
    jaccard = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return max(jaccard, SequenceMatcher(None, left, right).ratio())


class SemanticClaimClusterer:
    """Deterministic greedy clustering with an explicit strict lexical fallback."""

    method = "embedding"
    version = "cluster-v2"

    def __init__(self, embedder: EmbeddingService | None = None, *, threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
                 lexical_threshold: float = DEFAULT_LEXICAL_THRESHOLD) -> None:
        self.embedder = embedder
        self.threshold = threshold
        self.lexical_threshold = lexical_threshold
        self._embedding_cache: dict[tuple[str, str], list[float]] = {}

    async def cluster(self, answers: list[ModelAnswer], *, deadline: float | None = None) -> ClusteringOutcome:
        ordered = [(answer, claim) for answer in answers if answer.parse_status == "parsed" for claim in answer.claims if claim.id and normalize_claim_text(claim.claim)]
        if not ordered:
            return ClusteringOutcome(method="embedding" if self.embedder else "lexical", version=self.version, threshold=self.threshold, degraded=self.embedder is None)
        normalized = [normalize_claim_text(claim.claim) for _, claim in ordered]
        vectors: list[list[float]] | None = None
        warning: list[str] = []
        if self.embedder is not None:
            version = getattr(self.embedder, "version", "unknown")
            missing = [text for text in dict.fromkeys(normalized) if (version, text) not in self._embedding_cache]
            try:
                if missing:
                    embedded = await self.embedder.embed(missing, deadline=deadline)
                    if len(embedded) != len(missing) or any(not vector or any(not math.isfinite(value) for value in vector) for vector in embedded):
                        raise ValueError("invalid embedding shape")
                    self._embedding_cache.update({(version, text): vector for text, vector in zip(missing, embedded)})
                vectors = [self._embedding_cache[(version, text)] for text in normalized]
            except Exception:
                vectors = None
                warning = ["embedding clustering was unavailable; strict lexical fallback was used"]
        else:
            warning = ["embedding clustering is not configured; strict lexical fallback was used"]
        groups: list[list[int]] = []
        for index, text in enumerate(normalized):
            selected: int | None = None
            best = -1.0
            for group_index, members in enumerate(groups):
                similarities = [
                    _cosine(vectors[index], vectors[member]) if vectors is not None else _lexical_similarity(text, normalized[member])
                    for member in members
                ]
                score = sum(similarities) / len(similarities)
                boundary = self.threshold if vectors is not None else self.lexical_threshold
                if score >= boundary and score > best:
                    selected, best = group_index, score
            if selected is None:
                groups.append([index])
            else:
                groups[selected].append(index)
        clusters: list[ClaimCluster] = []
        for members in groups:
            # Confidence, then specificity/length, then original order.
            representative_index = max(members, key=lambda i: (ordered[i][1].confidence, len(normalized[i]), -i))
            representative = ordered[representative_index][1]
            support: list[str] = []
            for member in members:
                model = ordered[member][0].model
                if model not in support:
                    support.append(model)
            cluster_id = UUID(int=(representative.id.int ^ 0xC10C10) % (1 << 128))
            clusters.append(ClaimCluster(
                id=cluster_id,
                representative_text=representative.claim,
                representative_claim_id=representative.id,
                claim_ids=[ordered[member][1].id for member in members if ordered[member][1].id],
                supporting_models=support,
            ))
        return ClusteringOutcome(
            clusters=clusters,
            method="embedding" if vectors is not None else "lexical",
            version=f"{self.version}:{getattr(self.embedder, 'version', 'none')}",
            threshold=self.threshold if vectors is not None else self.lexical_threshold,
            degraded=vectors is None,
            warnings=warning,
        )


class OpenAIEmbeddingService:
    """Small OpenAI embeddings boundary; credentials never leave headers."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.version = f"openai:{model}:v1"

    async def embed(self, texts: list[str], *, deadline: float | None = None) -> list[list[float]]:
        timeout = 10.0
        if deadline is not None:
            import time
            timeout = min(timeout, max(0.001, deadline - time.monotonic()))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers={"authorization": f"Bearer {self.api_key}", "content-type": "application/json"},
                json={"model": self.model, "input": texts},
            )
        response.raise_for_status()
        data = response.json().get("data", [])
        return [list(item["embedding"]) for item in sorted(data, key=lambda item: item.get("index", 0))]
