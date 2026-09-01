---
id: 16-public-api-abuse-controls
title: Bounded public API controls
blocked_by:
  - 01-durable-query-tracer
risk: false
---

# 16: Bounded public API controls

**What to build:** An operator can configure and enforce anonymous public-flow boundaries for request bodies and fields, per-client rate and concurrency limits, allow-listed models, trusted-proxy interpretation, and safe outbound Evidence behavior. Standard correlated 422, 429, 502, and 503 envelopes remain machine-readable under bounded load, model-supplied URLs are never fetched, and only valid HTTP(S) Evidence URLs cross the public contract. This slice owns user story 62 and the public abuse-control, boundary-configuration, trusted-proxy, and outbound-URL decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] HTTP boundary tests prove configurable oversized-body and field rejection, allow-listed model selection, per-client rate and concurrency limits, trusted-proxy interpretation only for configured proxies, HTTP(S)-only Evidence, no arbitrary outbound source fetch, and exact correlated 422, 429, 502, and 503 envelopes.
- [ ] Bounded-load acceptance tests prove rejected or overloaded work does not open unbounded provider calls, exhaust workers, create a durable Report, or enter the Report cache, while permitted requests continue to use the same published success and partial-success contracts.
