---
id: 14-observability-privacy-abuse-controls
title: Observable, private, and bounded public flow
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 14: Observable, private, and bounded public flow

**What to build:** An operator can monitor correlated query, cache, Adapter, parse, clustering, Verifier, scoring, persistence, sandbox, cost, and feedback outcomes without raw Question, answer, feedback, secret, or upstream-body leakage. The anonymous public API enforces body, field, rate, concurrency, allow-list, outbound-URL, and trusted-proxy boundaries with standard 422/429/502/503 envelopes, while credentials remain environment-only, redacted from exceptions and stored diagnostics, and missing optional integrations never break liveness. This slice owns user stories 59–62 and the central settings, secret handling, structured telemetry, metrics, privacy, sanitization, and abuse-control decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] HTTP and telemetry acceptance tests inject credential-like and sensitive markers into requests and upstream failures and prove correlated events/metrics contain only hashes, lengths, categories, IDs, timing, usage, retry, parse, verification, cache, score, and sanitized status metadata; responses and persisted diagnostics contain no secret marker or raw private body.
- [ ] Boundary tests prove configurable oversized-body/field rejection, allow-listed models, per-client rate and concurrency limits, trusted-proxy interpretation, HTTP(S)-only Evidence, no arbitrary outbound source fetch, and exact correlated 422/429/502/503 envelopes under bounded load.
