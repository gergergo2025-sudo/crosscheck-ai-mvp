---
id: 05-claim-clustering
title: Deterministic Claim clustering
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 05: Deterministic Claim clustering

**What to build:** A user sees materially equivalent Claims grouped into stable Claim Clusters with a traceable representative and distinct supporting models. The report records the configured 0.85 semantic threshold and embedding version, counts duplicate Claims from one model once, and falls back to stricter deterministic lexical grouping with an explicit degraded warning when embeddings are unavailable. This slice owns user stories 22–26 and the normalization, embedding, representative-selection, and fallback clustering decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] HTTP acceptance fixtures prove Unicode and spacing normalization, one-support-per-model, stable representative tie-breaking and cluster order, and similarity cases immediately below, at, and above 0.85, including paraphrases that group and superficial overlaps that remain separate.
- [ ] A browser acceptance test proves each persisted Cluster displays its representative, supporting models, method/version/threshold, and a degraded lexical-fallback warning that does not overstate semantic agreement.
