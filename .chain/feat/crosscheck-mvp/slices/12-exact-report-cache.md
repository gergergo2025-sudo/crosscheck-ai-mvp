---
id: 12-exact-report-cache
title: Versioned exact Report cache
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 12: Versioned exact Report cache

**What to build:** A repeated canonical request returns the same durable complete or partial Report quickly with a cache indicator, while every result-affecting input and behavior version participates in a secret-free SHA-256 key. The configurable default TTL is 24 hours, refresh bypasses lookup and replaces only after a committed Report, concurrent misses single-flight, stale references miss safely, and Redis failure produces an uncached warning instead of failing the Question. This slice owns user stories 52–54 and all exact-cache behavior decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] HTTP integration tests with real PostgreSQL and Redis prove hit identity, cached flag, 86,400-second default TTL, expiry, refresh, concurrent single-flight, stale/missing Report references, and misses for changed Constraints, format, model order/effective set, prompt, Adapter, clustering, Verifier, or scoring version.
- [ ] HTTP and browser tests prove Redis outage continues uncached with a visible warning and that validation, configuration, rate-limit, and all-provider-failure responses are never cached or mistaken for durable Reports.
