---
id: 04-provider-resilience-deadline-cost
title: Provider resilience, deadline, and cost guard
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 04: Provider resilience, deadline, and cost guard

**What to build:** A user receives the best truthful partial Report when one or more selected providers time out, fail, lack credentials, or are skipped by the cost ceiling; calls run concurrently under one absolute query deadline, transient failures retry with bounded exponential backoff, and permanent failures stay isolated and sanitized. If no configured Adapter is usable or every dispatched Adapter fails, the API returns the specified 503 or 502 error instead of an empty Report. This slice owns user stories 9–14 and the Adapter retry, timeout, concurrency, partial-result, and cost-control decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] Mock-provider contract tests with a fake clock prove a 10-second maximum attempt, at most two retries after the initial call, exponential backoff with jitter, bounded Retry-After, retryable versus permanent classifications, cost-ceiling skips, sibling isolation, and cancellation at the absolute deadline.
- [ ] HTTP and browser acceptance tests prove wall time follows the slowest parallel call rather than their sum, one usable answer yields a durable partial 200 with visible sanitized provider statuses, and zero configured or zero successful providers yield the exact 503/502 envelopes without persisted or cached Reports.
