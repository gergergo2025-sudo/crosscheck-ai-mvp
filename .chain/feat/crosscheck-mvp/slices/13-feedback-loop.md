---
id: 13-feedback-loop
title: Append-only Report feedback
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 13: Append-only Report feedback

**What to build:** A user can mark a Report helpful or unhelpful, add a bounded comment, identify an erroneous Claim belonging to that Report, and suggest a better answer; successful feedback is appended with a stable ID and timestamp without mutating or rescoring the immutable Report. Invalid ownership and server failures preserve the user's typed input and return safe contract errors. This slice owns user stories 56–58 and the feedback API, relational validation, persistence, and UI decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] HTTP integration tests prove 201 creation, Report-not-found, Claim-not-in-Report, field bounds, multiple append-only submissions, foreign-key ownership, and injected write failure, while the original Report and score remain byte-for-byte unchanged.
- [ ] Browser acceptance tests prove helpful/unhelpful, Claim selection, comment, and suggested-answer flows confirm success and preserve typed values on validation or server failure without echoing excessive content.
