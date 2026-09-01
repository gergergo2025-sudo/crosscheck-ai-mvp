---
id: 10-verified-consensus-disagreements
title: Verified Consensus and explicit Disagreements
blocked_by:
  - 05-claim-clustering
  - 06-fact-evidence-verification
  - 09-scoring-recommendation
risk: true
---

# 10: Verified Consensus and explicit Disagreements

**What to build:** A user sees a Consensus item only when at least two distinct providers support a Cluster whose representative is independently verified, with Evidence and score credit traced back to the originating Claims and Model Answers. Singleton, unverified, unavailable, conflicting, and answer-level alternatives appear as Disagreements with inclusion reasons; repeated claims, lexical grouping alone, shared unsupported claims, and majority claims contradicted by stronger Evidence never manufacture Consensus, and general semantic opposition is not claimed. This slice owns user stories 38, 41, 46, and 47 and the verified-Consensus, limited-opposition, Disagreement, and consensus-score decisions.

**Blocked by:** 05-claim-clustering, 06-fact-evidence-verification, 09-scoring-recommendation.

- [ ] HTTP acceptance fixtures prove two-provider-plus-verification eligibility, one-Claim-per-model support, Evidence/Verification/Claim/Answer provenance, and consensus-score coverage, while every forbidden unverified, repeated, lexical-only, unsupported, and stronger-conflict case receives no Consensus or bonus.
- [ ] A browser acceptance test proves verified Consensus and each Disagreement class render separately with supporting models, Evidence, linked answers, and a human-readable reason, while oppose-model data is absent unless the narrow deterministic explicit-negation rule applies.
