---
id: 09-scoring-recommendation
title: Explainable scoring and recommendation
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 09: Explainable scoring and recommendation

**What to build:** A user sees each Model Answer's five PRD score components with numerator, denominator, applicability, configured weight, effective normalized weight, assurance caps, and final unrounded ordering. Only evidence categories that genuinely apply enter the denominator; the highest usable parsed answer is recommended at or above 0.60, deterministic configured order resolves exact ties with disclosure, and otherwise the Report returns an explicit insufficient-confidence state. This slice owns user stories 40 and 42–45 and the scoring, normalization, assurance-cap, tie, and recommendation decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] Table-driven scoring tests and HTTP fixtures cover no Claims, no Constraints, fact-only, code-only, mixed evidence, attempted-but-unverified checks, one usable provider, no independent verification, central conflict, degraded answers, configured weights, exact ties, and scores immediately below and at 0.60.
- [ ] A browser acceptance test proves complete component math and cap reasons are understandable, the winner uses the highest eligible unrounded score, ties are disclosed, degraded answers are excluded, and a null recommendation displays the prescribed inspection guidance.
