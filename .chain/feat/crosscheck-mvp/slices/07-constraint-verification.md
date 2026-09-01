---
id: 07-constraint-verification
title: Per-Constraint normalization and verification
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 07: Per-Constraint normalization and verification

**What to build:** A user can submit structured or supported natural-language Constraints and inspect a separate evidence-linked check for each budget, duration, weight, dimension, inclusion, exclusion, usage, or preference requirement. Numeric comparisons preserve units and currencies, unsupported conversions are refused, and missing or unevaluable answer parameters remain indeterminate with a reason rather than being silently satisfied. This slice owns user stories 3 and 35–37 and the Constraint normalization, extraction, comparison, and aggregation decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] HTTP acceptance tests cover structured and natural-language satisfied, violated, missing, incompatible unit/currency, strict exclusion, usage, and preference cases and prove every normalized expected value, observed value, comparator, reason, status, and provenance is persisted independently.
- [ ] A browser acceptance test proves every submitted Constraint appears once in both the relevant Model Answer and aggregate Report summary, with indeterminate results distinguished from failures and no satisfied item masking a violation.
