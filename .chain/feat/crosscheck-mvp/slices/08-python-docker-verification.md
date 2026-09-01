---
id: 08-python-docker-verification
title: Isolated Python code verification
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 08: Isolated Python code verification

**What to build:** A developer can inspect behavioral evidence for a clearly delimited Python answer executed with explicit safe tests or deterministic tests for a small recognized-task allow-list in an ephemeral, pinned local Docker sandbox. The sandbox fails closed without Docker or a safe test contract, disables network and host access, enforces resource and output limits, and reports bounded execution status, passed/total tests, output, and sanitized errors; unsupported Claim types are explicitly not applicable. This slice owns user stories 31–34 and 39 and the Code Verifier, sandbox, safe-test-selection, and unsupported-Verifier decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] Real Docker integration tests prove a passing recognized algorithm plus syntax error, failed tests, wall timeout, output flood, network denial, process/fork pressure, memory pressure, filesystem attempts, zero tests, missing Docker, and no safe contract produce distinct bounded statuses without executing code in the backend process.
- [ ] HTTP and browser acceptance tests prove execution Evidence is attached to the originating Claim and Model Answer, contributes passed/total counts only when tests ran, and renders unavailable and not-applicable states without implying correctness.
